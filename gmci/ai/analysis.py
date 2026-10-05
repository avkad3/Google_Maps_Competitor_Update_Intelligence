"""Post-level and repository-level content analysis.

Each post gets: main topic, sub-topic, keywords, content type, call to action and offer pattern.
An LLM provider does this in batches when a key is configured; the offline analyser (topic
vocabulary + TF-IDF keywords + regex offer detection) fills in anything the LLM did not return,
so analysis always completes.
"""
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date

from ..db import jdump, jload, now, row, rows
from ..repository import project_business_ids, save_analysis
from ..textutil import ngrams, tokens
from . import providers
from .taxonomy import CONTENT_TYPES, CTA_PATTERNS, INDUSTRY, guess_industry_key, topics_for

BATCH = 15
WEAK_KEYWORDS = {"tips", "offer", "flat", "save", "deal", "card", "member", "clean", "said", "loved", "stars", "glow",
                 "review", "open", "hours", "white", "launch", "newly", "safety", "festive", "festival", "result",
                 "% off", "precision", "professionnel"}

OFFER_RE = re.compile(
    r"(\d{1,2}\s?%\s?off|flat\s+(?:₹|rs\.?\s?)?\d+[\w%]*\s*(?:off)?|(?:₹|rs\.?\s?)\s?\d[\d,]*(?:/-)?|buy\s+(?:1|one)\s+get\s+(?:1|one)(?:\s+free)?|"
    r"free\s+(?!of\b)[a-z\-]{3,15}(?:\s+(?:check(?:-up)?|consultation|scan|session|accessory|nail art|application))?|"
    r"complimentary\s+[a-z\-]{3,15}|upto\s+\d+%|up to\s+\d+%)", re.I)


# ------------------------------------------------------------------ offline analyser

class OfflineAnalyser:
    def __init__(self, industry: str, corpus: list):
        self.topics = topics_for(industry)
        self.industry_topics = set(INDUSTRY.get(guess_industry_key(industry), {}))
        docs = [set(tokens(t)) | set(ngrams(tokens(t))) for t in corpus] or [set()]
        self.n_docs = len(docs)
        self.df = Counter(term for d in docs for term in d)

    def _score(self, text, vocab):
        low = text.lower()
        scores = {}
        for name, words in vocab.items():
            hits = [w for w in words if w in low]
            if hits:
                scores[name] = sum(2 if " " in w else 1 for w in hits) * (1.3 if name in getattr(self, "industry_topics", ()) else 1)
        return sorted(scores.items(), key=lambda kv: -kv[1])

    def keywords(self, text, limit=6):
        """Search-style keywords: vocabulary phrases found in the post, then distinctive single words."""
        low = text.lower()
        picked = []
        for words in self.topics.values():
            for w in words:
                if len(w) > 3 and w in low and w not in picked and w not in WEAK_KEYWORDS:
                    picked.append(w)
        picked.sort(key=lambda w: (-(" " in w), -len(w)))
        picked = picked[:limit - 2]
        scored = []
        for term in set(tokens(text)):
            df = self.df.get(term, 0)
            if len(term) < 4 or df < 2:
                continue
            scored.append((math.log((1 + self.n_docs) / (1 + df)), term))
        for _, term in sorted(scored, reverse=True):
            if len(picked) >= limit:
                break
            if not any(term in p for p in picked):
                picked.append(term)
        return picked

    def analyse(self, post: dict) -> dict:
        text = post["text"]
        ranked = self._score(text, self.topics)
        main = ranked[0][0] if ranked else "General Update"
        sub = ranked[1][0] if len(ranked) > 1 else ""
        ctype = self._score(text, CONTENT_TYPES)
        cta = post.get("cta_label") or ""
        if not cta:
            c = self._score(text, CTA_PATTERNS)
            cta = c[0][0] if c else "None"
        offers = OFFER_RE.findall(text)
        return {"main_topic": main, "sub_topic": sub, "keywords": self.keywords(text),
                "content_type": ctype[0][0] if ctype else "Update", "cta": cta,
                "offer": "; ".join(dict.fromkeys(o.strip() for o in offers))[:120] if offers else ""}


# ------------------------------------------------------------------ LLM analyser

SYSTEM = ("You are a local-marketing analyst who classifies Google Business Profile (Google Maps) updates. "
          "Answer with JSON only.")


def _llm_batch(batch, industry, topic_names, preferred):
    lines = [{"id": p["id"], "business": p["business_name"], "cta_button": p.get("cta_label") or "",
              "text": p["text"][:900]} for p in batch]
    prompt = (
        f"Industry: {industry or 'local business'}.\n"
        f"Preferred topic names (reuse one when it fits, otherwise create a short Title Case topic): {', '.join(topic_names)}.\n"
        "For every post return an object with: id, main_topic, sub_topic (more specific, 2-5 words), keywords "
        "(3-6 lowercase search phrases a customer would use), content_type (one of: Offer / Promotion, Educational Tip, "
        "Before/After Showcase, Testimonial, Service Launch, Event, Greeting, Announcement, Update), cta (the call to "
        "action, or None), offer (the promotion mechanic such as '20% off' or 'free consultation', or empty).\n"
        'Return {"posts": [...]}.\n\nPosts:\n' + json.dumps(lines, ensure_ascii=False))
    data, provider = providers.llm_json(SYSTEM, prompt, preferred, temperature=0.2)
    if not data:
        return {}, provider
    items = data.get("posts", data) if isinstance(data, dict) else data
    out = {}
    for it in items if isinstance(items, list) else []:
        try:
            out[int(it.get("id"))] = it
        except (TypeError, ValueError, AttributeError):
            continue
    return out, provider


def analyse_project(conn, project_id, preferred: str = "", reanalyse: bool = False, progress=None) -> dict:
    project = row(conn, "SELECT * FROM projects WHERE id=?", (project_id,))
    ids = project_business_ids(conn, project_id, include_own=True)
    if not ids:
        return {"analysed": 0, "provider": "none"}
    marks = ",".join("?" * len(ids))
    posts = rows(conn, f"""SELECT p.*, b.name AS business_name, a.post_id AS done FROM posts p
                           JOIN businesses b ON b.id = p.business_id LEFT JOIN post_analysis a ON a.post_id = p.id
                           WHERE p.business_id IN ({marks}) ORDER BY p.id""", ids)
    corpus = [p["text"] for p in posts]
    todo = [p for p in posts if reanalyse or not p["done"]]
    offline = OfflineAnalyser(project["industry"], corpus)
    topic_names = list(offline.topics.keys())
    used = Counter()
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        llm, provider = _llm_batch(batch, project["industry"], topic_names, preferred) if preferred != "offline" else ({}, "offline")
        for p in batch:
            base = offline.analyse(p)
            got = llm.get(p["id"])
            if got:
                merged = {k: (got.get(k) if got.get(k) not in (None, "", []) else base[k]) for k in base}
                if isinstance(merged["keywords"], str):
                    merged["keywords"] = [k.strip() for k in merged["keywords"].split(",") if k.strip()]
                merged["keywords"] = [str(k).lower() for k in merged["keywords"]][:8]
                if str(merged.get("cta", "")).lower() in {"none", "null", "n/a"}:
                    merged["cta"] = "None"
                save_analysis(conn, p["id"], merged, provider)
                used[provider] += 1
            else:
                save_analysis(conn, p["id"], base, "offline")
                used["offline"] += 1
        if progress:
            progress(min(i + BATCH, len(todo)), len(todo))
    summary = repository_summary(conn, project_id, preferred)
    provider_label = ", ".join(f"{k} ({v})" for k, v in used.items()) or "already analysed"
    conn.execute("INSERT INTO analysis_runs (project_id, provider, posts_analyzed, summary, created_at) VALUES (?, ?, ?, ?, ?)",
                 (project_id, provider_label, len(todo), jdump(summary), now()))
    return {"analysed": len(todo), "provider": provider_label, "summary": summary}


# ------------------------------------------------------------------ repository-level insights

def _posts_with_analysis(conn, business_ids):
    if not business_ids:
        return []
    marks = ",".join("?" * len(business_ids))
    return rows(conn, f"""SELECT p.id, p.business_id, p.text, p.published_at, p.scraped_at, b.name AS business_name,
                                 a.main_topic, a.sub_topic, a.keywords, a.content_type, a.cta, a.offer
                          FROM posts p JOIN businesses b ON b.id = p.business_id
                          LEFT JOIN post_analysis a ON a.post_id = p.id WHERE p.business_id IN ({marks})""", business_ids)


def competitor_patterns(conn, project_id):
    posts = _posts_with_analysis(conn, project_business_ids(conn, project_id))
    by_biz = defaultdict(list)
    for p in posts:
        by_biz[(p["business_id"], p["business_name"])].append(p)
    out = []
    for (bid, name), items in by_biz.items():
        dates = sorted(d for d in (p["published_at"] for p in items) if d)
        span_days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days if len(dates) > 1 else 0
        months = max(span_days / 30.4, 1)
        topics = Counter(p["main_topic"] for p in items if p["main_topic"])
        types = Counter(p["content_type"] for p in items if p["content_type"])
        out.append({
            "business_id": bid, "name": name, "posts": len(items),
            "per_month": round(len(items) / months, 1),
            "avg_gap_days": round(span_days / (len(dates) - 1), 1) if len(dates) > 1 else None,
            "first": dates[0] if dates else "", "last": dates[-1] if dates else "",
            "top_topics": topics.most_common(3), "top_type": types.most_common(1)[0][0] if types else "",
            "offer_share": round(100 * sum(1 for p in items if p["offer"]) / len(items)),
        })
    return sorted(out, key=lambda r: -r["posts"])


def repository_summary(conn, project_id, preferred: str = "") -> dict:
    posts = _posts_with_analysis(conn, project_business_ids(conn, project_id))
    analysed = [p for p in posts if p["main_topic"]]
    topic_c = Counter(p["main_topic"] for p in analysed)
    sub_c = Counter(p["sub_topic"] for p in analysed if p["sub_topic"])
    type_c = Counter(p["content_type"] for p in analysed)
    cta_c = Counter(p["cta"] for p in analysed if p["cta"] and p["cta"] != "None")
    kw_c = Counter(k for p in analysed for k in jload(p["keywords"]))
    offer_c = Counter()
    for p in analysed:
        for o in (p["offer"] or "").split(";"):
            o = re.sub(r"\d[\d,]*", "N", o.strip().lower())
            if o:
                offer_c[o] += 1
    months = Counter((p["published_at"] or "")[:7] for p in posts if p["published_at"])
    summary = {
        "posts": len(posts), "analysed": len(analysed),
        "topics": topic_c.most_common(15), "sub_topics": sub_c.most_common(15),
        "content_types": type_c.most_common(), "ctas": cta_c.most_common(8),
        "keywords": kw_c.most_common(25), "offer_patterns": offer_c.most_common(10),
        "posts_per_month": sorted(months.items()),
        "competitors": competitor_patterns(conn, project_id),
        "insights": [], "insights_provider": "offline",
    }
    summary["insights"] = _offline_insights(summary)
    data, provider = providers.llm_json(
        "You are a Google Business Profile content strategist. Answer with JSON only.",
        "Here are statistics about competitor Google Maps updates for one local business market:\n"
        + json.dumps({k: summary[k] for k in ("topics", "content_types", "ctas", "keywords", "offer_patterns",
                                                   "posts_per_month")}, ensure_ascii=False)
        + "\nCompetitor publishing patterns: "
        + json.dumps([{k: c[k] for k in ("name", "posts", "per_month", "top_topics", "offer_share")} for c in summary["competitors"]],
                     ensure_ascii=False)
        + '\nReturn {"insights": ["5-7 short, specific, data-backed observations a business owner can act on"]}',
        preferred if preferred != "offline" else "offline", temperature=0.4) if preferred != "offline" else (None, "offline")
    if data and isinstance(data.get("insights"), list) and data["insights"]:
        summary["insights"] = [str(x) for x in data["insights"]][:8]
        summary["insights_provider"] = provider
    return summary


def _offline_insights(s):
    out = []
    if s["topics"]:
        t, n = s["topics"][0]
        out.append(f"'{t}' is the most published topic ({n} of {s['analysed']} posts, "
                   f"{round(100 * n / max(s['analysed'], 1))}%).")
    if s["content_types"]:
        t, n = s["content_types"][0]
        out.append(f"{t} is the dominant content format ({round(100 * n / max(s['analysed'], 1))}% of posts).")
    if s["offer_patterns"]:
        out.append("Most common promotion mechanics: " + ", ".join(o for o, _ in s["offer_patterns"][:3]) + ".")
    if s["ctas"]:
        out.append(f"Competitors mostly ask customers to '{s['ctas'][0][0]}'.")
    comps = s["competitors"]
    if comps:
        top = max(comps, key=lambda c: c["per_month"])
        out.append(f"{top['name']} publishes most often (about {top['per_month']} updates a month).")
        quiet = [c["name"] for c in comps if c["last"] and c["last"] < date.today().replace(day=1).isoformat()[:7]]
        if quiet:
            out.append(f"{len(quiet)} competitor(s) have not posted this month, a window to stand out.")
    if s["keywords"]:
        out.append("Recurring keywords: " + ", ".join(k for k, _ in s["keywords"][:6]) + ".")
    return out


def latest_summary(conn, project_id):
    r = row(conn, "SELECT * FROM analysis_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (project_id,))
    if not r:
        return None
    r["summary"] = jload(r["summary"], {})
    return r
