"""AI provider layer with automatic model discovery and failover.

Supported: Google Gemini, Groq, xAI Grok, OpenRouter (all have free or developer tiers), plus an
``offline`` provider that never calls the network so the app keeps working without keys.

Keys are read from environment variables only and are never sent to the browser or logged.
"""
import base64
import json
import re
import threading
import time

import requests

from .. import config

TIMEOUT = 60


class ProviderError(Exception):
    pass


def _extract_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except ValueError:
            pass
    raise ProviderError("Model did not return valid JSON")


class Provider:
    name = "base"
    label = "Base"
    env_key = ""
    preferences: tuple = ()
    default_model = ""

    def __init__(self):
        self._model = None
        self.last_error = ""
        self.last_used = ""
        self.models_seen: list = []

    @property
    def key(self):
        return config.env(self.env_key)

    def configured(self) -> bool:
        return bool(self.key)

    def model(self) -> str:
        override = config.env(f"{self.name.upper()}_MODEL")
        if override:
            return override
        if self._model is None:
            self._model = self.discover_model() or self.default_model
        return self._model

    def discover_model(self) -> str:
        """Automatic model discovery: list the account's models and pick the best match."""
        try:
            ids = self.list_models()
        except Exception as exc:  # discovery failure is not fatal
            self.last_error = f"model discovery failed: {exc}"
            return ""
        self.models_seen = ids
        for pattern in self.preferences:
            for mid in ids:
                if re.search(pattern, mid):
                    return mid
        return ids[0] if ids else ""

    def list_models(self) -> list:
        return []

    def complete(self, system: str, prompt: str, want_json=True, temperature=0.7) -> str:
        raise NotImplementedError

    def complete_json(self, system: str, prompt: str, temperature=0.7):
        return _extract_json(self.complete(system, prompt, True, temperature))

    def status(self) -> dict:
        return {"name": self.name, "label": self.label, "configured": self.configured(), "env_key": self.env_key,
                "model": (self._model or config.env(f"{self.name.upper()}_MODEL") or "auto") if self.configured() else "",
                "last_error": self.last_error, "last_used": self.last_used}


class OpenAICompatible(Provider):
    base_url = ""

    def _headers(self):
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def list_models(self):
        r = requests.get(f"{self.base_url}/models", headers=self._headers(), timeout=20)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def complete(self, system, prompt, want_json=True, temperature=0.7):
        body = {"model": self.model(), "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        if want_json:
            body["response_format"] = {"type": "json_object"}
        r = requests.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body, timeout=TIMEOUT)
        if r.status_code == 400 and want_json:  # some models reject response_format
            body.pop("response_format")
            r = requests.post(f"{self.base_url}/chat/completions", headers=self._headers(), json=body, timeout=TIMEOUT)
        if r.status_code >= 400:
            raise ProviderError(f"{self.label} HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"]


class Groq(OpenAICompatible):
    name, label, env_key = "groq", "Groq", "GROQ_API_KEY"
    base_url = "https://api.groq.com/openai/v1"
    preferences = (r"llama-3\.3-70b", r"llama-3\.1-70b", r"gpt-oss-120b", r"llama.*70b", r"llama")
    default_model = "llama-3.3-70b-versatile"


class XAI(OpenAICompatible):
    name, label, env_key = "xai", "xAI Grok", "XAI_API_KEY"
    base_url = "https://api.x.ai/v1"
    preferences = (r"grok-\d+-mini", r"grok-\d+(?!.*image)", r"grok")
    default_model = "grok-3-mini"


class OpenRouter(OpenAICompatible):
    name, label, env_key = "openrouter", "OpenRouter", "OPENROUTER_API_KEY"
    base_url = "https://openrouter.ai/api/v1"
    preferences = (r"llama-3\.3-70b.*:free", r"gemma.*:free", r"mistral.*:free", r":free")
    default_model = "meta-llama/llama-3.3-70b-instruct:free"


class Gemini(Provider):
    name, label, env_key = "gemini", "Google Gemini", "GEMINI_API_KEY"
    base = "https://generativelanguage.googleapis.com/v1beta"
    default_model = "gemini-flash-latest"
    # Google retires dated models (e.g. gemini-2.5-flash) while still listing them, so prefer the
    # always-current alias, then the newest stable Flash, and skip any model that answers "no longer available".
    SKIP = re.compile(r"image|tts|live|audio|embed|omni|research|customtools|preview|exp", re.I)

    def __init__(self):
        super().__init__()
        self.retired: set = set()

    @staticmethod
    def _version(mid):
        m = re.match(r"gemini-(\d+(?:\.\d+)?)-", mid)
        return float(m.group(1)) if m else 0.0

    def candidates(self, ids=None) -> list:
        ids = [i for i in (ids if ids is not None else self.models_seen) if i not in self.retired]
        flash = sorted((i for i in ids if re.fullmatch(r"gemini-\d+(\.\d+)?-flash", i)), key=self._version, reverse=True)
        lite = sorted((i for i in ids if re.fullmatch(r"gemini-\d+(\.\d+)?-flash-lite", i)), key=self._version, reverse=True)
        other = [i for i in ids if "flash" in i and not self.SKIP.search(i) and i not in flash + lite]
        alias = [i for i in ("gemini-flash-latest", "gemini-flash-lite-latest") if i in ids]
        return alias[:1] + flash + alias[1:] + lite + other

    def discover_model(self) -> str:
        try:
            self.models_seen = self.list_models()
        except Exception as exc:  # discovery failure is not fatal
            self.last_error = f"model discovery failed: {exc}"
            return ""
        return next(iter(self.candidates()), "")

    def image_model(self) -> str:
        override = config.env("GEMINI_IMAGE_MODEL")
        if override:
            return override
        if not self.models_seen:
            self.discover_model()
        imgs = [i for i in self.models_seen if re.fullmatch(r"gemini-\d+(\.\d+)?-flash-image", i) and i not in self.retired]
        return max(imgs, key=self._version) if imgs else "gemini-2.5-flash-image"

    def _headers(self):
        return {"x-goog-api-key": self.key, "Content-Type": "application/json"}

    def list_models(self):
        r = requests.get(f"{self.base}/models?pageSize=200", headers=self._headers(), timeout=20)
        r.raise_for_status()
        return [m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]

    def complete(self, system, prompt, want_json=True, temperature=0.7):
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature}}
        if want_json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        # Retired model (404): drop it for good. Overloaded model (503/429): try the next one for this request.
        tried = []
        for _ in range(4):
            model = self.model()
            tried.append(model)
            r = requests.post(f"{self.base}/models/{model}:generateContent", headers=self._headers(), json=body,
                              timeout=TIMEOUT)
            if r.status_code not in (404, 429, 503) or config.env("GEMINI_MODEL"):
                break
            if r.status_code == 404:
                self.retired.add(model)
            nxt = next((c for c in self.candidates() if c not in tried), None)
            if not nxt:
                break
            self._model = nxt  # stays on the working model; the Test button re-picks the preferred one
        if r.status_code >= 400:
            raise ProviderError(f"Gemini HTTP {r.status_code} ({model}): {r.text[:200]}")
        cands = r.json().get("candidates") or []
        if not cands:
            raise ProviderError("Gemini returned no candidates (possibly blocked)")
        return "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))

    def generate_image(self, prompt: str) -> bytes | None:
        """AI image generation where the account supports it; returns PNG bytes or None."""
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
        for _ in range(3):
            model = self.image_model()
            r = requests.post(f"{self.base}/models/{model}:generateContent", headers=self._headers(), json=body, timeout=TIMEOUT)
            if r.status_code == 404 and not config.env("GEMINI_IMAGE_MODEL") and model not in self.retired:
                self.retired.add(model)
                continue
            break
        if r.status_code >= 400:
            raise ProviderError(f"Gemini image HTTP {r.status_code}: {r.text[:160]}")
        for cand in r.json().get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                data = part.get("inlineData") or part.get("inline_data")
                if data and data.get("data"):
                    return base64.b64decode(data["data"])
        return None


class Offline(Provider):
    """Deterministic, network-free provider. The analysis/generation modules implement its logic."""
    name, label = "offline", "Built-in offline analyser"

    def configured(self):
        return True

    def model(self):
        return "rules + repository statistics"

    def complete(self, *a, **k):
        raise ProviderError("offline provider has no language model")

    def status(self):
        return {"name": self.name, "label": self.label, "configured": True, "env_key": "", "model": self.model(),
                "last_error": "", "last_used": self.last_used}


PROVIDERS = {p.name: p for p in (Gemini(), Groq(), XAI(), OpenRouter(), Offline())}
_lock = threading.Lock()


def order(preferred: str = "") -> list:
    names = [n.strip() for n in config.env("AI_PROVIDER_ORDER", "gemini,groq,xai,openrouter,offline").split(",") if n.strip()]
    if preferred and preferred in PROVIDERS:
        names = [preferred] + [n for n in names if n != preferred]
    if "offline" not in names:
        names.append("offline")
    return [PROVIDERS[n] for n in names if n in PROVIDERS]


def llm_json(system: str, prompt: str, preferred: str = "", temperature=0.7):
    """Try configured LLM providers in order. Returns ``(data, provider_name)`` or ``(None, 'offline')``."""
    for p in order(preferred):
        if p.name == "offline":
            break
        if not p.configured():
            continue
        try:
            data = p.complete_json(system, prompt, temperature)
            p.last_used = time.strftime("%Y-%m-%d %H:%M:%S")
            p.last_error = ""
            return data, f"{p.name}:{p.model()}"
        except Exception as exc:  # fail over to the next provider
            p.last_error = str(exc)[:300]
    PROVIDERS["offline"].last_used = time.strftime("%Y-%m-%d %H:%M:%S")
    return None, "offline"


def statuses():
    return [p.status() for p in order()]


def test_provider(name: str) -> dict:
    p = PROVIDERS.get(name)
    if not p:
        return {"ok": False, "message": "Unknown provider"}
    if name == "offline":
        return {"ok": True, "message": "Offline analyser is always available"}
    if not p.configured():
        return {"ok": False, "message": f"Set {p.env_key} in the server environment"}
    try:
        p._model = None
        if hasattr(p, "retired"):
            p.retired.clear()
        data = p.complete_json("Reply with JSON only.", 'Return {"ok": true, "provider": "<your name>"}', 0)
        return {"ok": True, "message": f"Model {p.model()} answered: {json.dumps(data)[:120]}",
                "models": p.models_seen[:30]}
    except Exception as exc:
        p.last_error = str(exc)[:300]
        return {"ok": False, "message": p.last_error}
