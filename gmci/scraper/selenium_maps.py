"""Live Google Maps scraper (Selenium + Chrome/Chromium, or Microsoft Edge when Chrome is missing).

Flow per competitor
1. Open the profile URL (or search Maps for "name address" when no URL is stored).
2. Accept/close the cookie consent screen if it appears.
3. Check for CAPTCHA / "unusual traffic" / sign-in verification and raise ``VerificationRequired``.
4. Read header facts (name, category, rating, address).
5. Open the "Updates" tab when it exists (falls back to the "From the owner" block on Overview).
6. Scroll the panel to load more updates, expand "More" buttons, and extract each update card.

Google changes Maps markup often, so extraction avoids obfuscated class names. Update cards are
found structurally: a node whose text is a relative date ("2 weeks ago") is the anchor, and the
nearest ancestor that also holds a meaningful block of text is the card.

Reliability measures (all permitted): a persistent Chrome profile so cookies from a manual
verification are reused, realistic pacing with jitter between profiles, one browser per run,
and a hard stop that asks a human instead of retrying when Google challenges the session.
"""
import os
import random
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote_plus

from .. import config
from . import ScrapedProfile, ScrapeError, VerificationRequired

CAPTCHA_MARKERS = (
    "unusual traffic", "not a robot", "recaptcha", "verify it's you", "verify it’s you",
    "our systems have detected", "solve this captcha", "sorry/index",
)
CTA_WORDS = ("learn more", "book", "call now", "call", "order online", "order", "buy", "sign up",
             "get offer", "redeem", "reserve", "shop", "visit", "register", "claim")

# Run inside the page. Returns a list of {text, date, images, links} for update cards.
EXTRACT_JS = r"""
const mains = document.querySelectorAll('div[role="main"]');   // after a search the results list stays as the first pane
const root = mains[mains.length - 1] || document.body;
const dateRe = /^(?:(?:a|an|one|\d+)\s+(?:minute|hour|day|week|month|year)s?\s+ago|today|yesterday|\d{1,2}\s+\w{3,9}\s+\d{4}|\w{3,9}\s+\d{1,2},\s+\d{4})$/i;
const seen = new Set();
const cards = [];
for (const el of root.querySelectorAll('span, div, time')) {
  if (el.children.length > 0) continue;   // leaf nodes only
  const t = (el.innerText || '').trim();
  if (!t || t.length > 30 || !dateRe.test(t)) continue;
  // Reviews also carry dates; skip anything inside a review block.
  if (el.closest('[data-review-id], [jsaction*="review"]')) continue;
  // Expanded post list: the card is the nearest ancestor holding the post's share button.
  let card = null;
  for (let a = el.parentElement, i = 0; a && a !== root && i < 7; a = a.parentElement, i++) {
    if (a.querySelector('[data-sharing-url]')) { card = a; break; }
  }
  // The share button sits in the card header, so widen to the whole post (image, text, CTA)
  // while the parent still holds only this one post.
  while (card && card.parentElement && card.parentElement !== root &&
         card.parentElement.querySelectorAll('[data-sharing-url]').length === 1) card = card.parentElement;
  // Otherwise climb while the text stays close to the date (preview cards, older layouts).
  if (!card) {
    card = el.parentElement; let depth = 0;
    while (card && card !== root && depth < 8) {
      const txt = (card.innerText || '').trim();
      if (txt.length - t.length > 40) break;
      card = card.parentElement; depth++;
    }
  }
  if (!card || card === root || seen.has(card)) continue;
  // Reject a container that holds several dated cards (we climbed too far).
  const dates = [...card.querySelectorAll('span, div, time')].filter(n => n.children.length === 0 && dateRe.test((n.innerText||'').trim()));
  if (dates.length > 1) continue;
  seen.add(card);
  const images = [...card.querySelectorAll('img')].map(i => i.src || i.getAttribute('data-src') || '')
     .filter(s => s && /googleusercontent|ggpht|gstatic.com\/(?!images\/icons)/.test(s))
     .filter(s => !/\/photo\.jpg|=s\d{2,3}-c|\/s\d{2,3}-c/.test(s));   // skip the business avatar
  const bg = [...card.querySelectorAll('[style*="background-image"]')]
     .map(n => (n.style.backgroundImage.match(/url\(["']?(.*?)["']?\)/) || [])[1]).filter(Boolean);
  const links = [...card.querySelectorAll('a[href], button[aria-label]')].map(a => ({
      label: (a.innerText || a.getAttribute('aria-label') || '').trim(), href: a.href || a.getAttribute('data-href') || ''}));
  const share = card.querySelector('[data-sharing-url]');
  cards.push({text: card.innerText.trim(), date: t, images: [...new Set(images.concat(bg))], links,
              share: share ? share.getAttribute('data-sharing-url') : ''});
}
return cards;
"""


def _windows_paths(*parts):
    """Standard install locations under Program Files / LocalAppData (Windows only)."""
    roots = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    return [str(Path(r, *parts)) for r in roots if r]


def _find_chrome():
    for candidate in (config.env("CHROME_BINARY"), shutil.which("google-chrome"), shutil.which("chromium"),
                      shutil.which("chromium-browser"), shutil.which("chrome"),
                      *_windows_paths("Google", "Chrome", "Application", "chrome.exe"),
                      "/opt/pw-browsers/chromium/chrome-linux/chrome"):
        if candidate and Path(candidate).exists():
            return candidate
    base = Path("/opt/pw-browsers")
    if base.exists():
        for p in sorted(base.glob("chromium-*/chrome-linux*/chrome")):
            return str(p)
    return None


def _find_edge():
    for candidate in (config.env("EDGE_BINARY"), shutil.which("msedge"), shutil.which("microsoft-edge"),
                      shutil.which("microsoft-edge-stable"),
                      *_windows_paths("Microsoft", "Edge", "Application", "msedge.exe"),
                      "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def find_browser():
    """Pick the browser for live scraping: ("chrome" | "edge", binary path) or (None, None).

    GMCI_BROWSER=chrome|edge forces one; otherwise Chrome is preferred and Edge is the fallback.
    """
    wanted = config.env("GMCI_BROWSER").lower()
    if wanted != "edge":
        chrome = _find_chrome()
        if chrome:
            return "chrome", chrome
    if wanted != "chrome":
        edge = _find_edge()
        if edge:
            return "edge", edge
    return None, None


class MapsScraper:
    def __init__(self, headless: bool | None = None, log=print, screenshot_prefix: str = "run"):
        self.headless = config.HEADLESS if headless is None else headless
        self.log = log
        self.prefix = screenshot_prefix
        self.driver = None

    # -------------------------------------------------------------- browser
    def start(self):
        try:
            from selenium import webdriver
        except ImportError as exc:  # pragma: no cover
            raise ScrapeError("Selenium is not installed (pip install selenium)") from exc
        kind, binary = find_browser()
        if not kind:
            raise ScrapeError("No Chrome, Chromium or Edge browser found (set CHROME_BINARY or EDGE_BINARY)")
        if kind == "edge":
            from selenium.webdriver.edge.service import Service
            opts, driver_cls, driver_env, label = webdriver.EdgeOptions(), webdriver.Edge, "EDGEDRIVER_PATH", "Edge"
        else:
            from selenium.webdriver.chrome.service import Service
            opts, driver_cls, driver_env, label = webdriver.ChromeOptions(), webdriver.Chrome, "CHROMEDRIVER_PATH", "Chrome"
        if self.headless:
            opts.add_argument("--headless=new")
        for arg in ("--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,1000", "--lang=en-US",
                    "--disable-blink-features=AutomationControlled"):
            opts.add_argument(arg)
        opts.add_experimental_option("prefs", {"intl.accept_languages": "en-US,en"})
        if config.CHROME_PROFILE:
            # Chrome and Edge profiles are not interchangeable, so Edge gets its own folder.
            profile = config.CHROME_PROFILE + ("-edge" if kind == "edge" else "")
            Path(profile).mkdir(parents=True, exist_ok=True)
            opts.add_argument(f"--user-data-dir={profile}")
        opts.binary_location = binary
        driver_path = config.env(driver_env)  # empty: Selenium Manager downloads a matching driver
        service = Service(executable_path=driver_path) if driver_path else Service()
        try:
            self.driver = driver_cls(service=service, options=opts)
        except Exception as exc:
            raise ScrapeError(f"Could not start {label}: {str(exc).splitlines()[0]}") from exc
        self.log(f"Browser: {label} ({binary})")
        self.driver.set_page_load_timeout(45)
        return self

    def stop(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    def screenshot(self, tag: str) -> str:
        if not self.driver:
            return ""
        path = config.SCREENSHOT_DIR / f"{self.prefix}-{tag}-{int(time.time())}.png"
        try:
            self.driver.save_screenshot(str(path))
            return str(path)
        except Exception:
            return ""

    # Remote verification console: a human solves the challenge through screenshots.
    def click_at(self, x: int, y: int):
        self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                                                 "button": "left", "clickCount": 1})
        self.driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                                                 "button": "left", "clickCount": 1})

    def type_text(self, text: str, enter: bool = False):
        self.driver.execute_cdp_cmd("Input.insertText", {"text": text})
        if enter:
            for kind in ("keyDown", "keyUp"):
                self.driver.execute_cdp_cmd("Input.dispatchKeyEvent", {"type": kind, "key": "Enter", "code": "Enter",
                                                                       "windowsVirtualKeyCode": 13})

    def viewport(self):
        return self.driver.execute_script("return [window.innerWidth, window.innerHeight]")

    # -------------------------------------------------------------- checks
    def _pause(self, lo=1.2, hi=2.6):
        time.sleep(random.uniform(lo, hi))

    def _handle_consent(self):
        d = self.driver
        if "consent." not in d.current_url and "before you continue" not in d.page_source[:20000].lower():
            return
        for label in ("Reject all", "Accept all", "I agree", "Alle ablehnen", "Tout refuser"):
            try:
                btns = d.find_elements("xpath", f"//button[.//span[normalize-space()='{label}'] or normalize-space()='{label}']")
                if btns:
                    btns[0].click()
                    self.log("Closed Google cookie consent screen")
                    self._pause()
                    return
            except Exception:
                continue

    def check_verification(self):
        d = self.driver
        url = d.current_url.lower()
        body = ""
        try:
            body = d.find_element("tag name", "body").text.lower()[:5000]
        except Exception:
            pass
        has_recaptcha = bool(d.find_elements("css selector", "iframe[src*='recaptcha'], #captcha-form, form#captcha"))
        if "/sorry/" in url or has_recaptcha or any(m in body for m in CAPTCHA_MARKERS):
            shot = self.screenshot("verification")
            raise VerificationRequired("Google is asking for verification (CAPTCHA / unusual traffic)", d.current_url, shot)
        if "accounts.google.com" in url:
            shot = self.screenshot("signin")
            raise VerificationRequired("Google redirected to a sign-in / verify-it's-you page", d.current_url, shot)

    # -------------------------------------------------------------- profile
    def open_profile(self, name: str, maps_url: str = "", address: str = ""):
        d = self.driver
        target = maps_url if maps_url and "google." in maps_url else \
            f"https://www.google.com/maps/search/{quote_plus((name + ' ' + (address or '')).strip())}?hl=en"
        if "hl=" not in target:
            target += ("&" if "?" in target else "?") + "hl=en"
        self.log(f"Opening {target}")
        d.get(target)
        self._pause(2.0, 3.5)
        self._handle_consent()
        self.check_verification()
        # A search can land on a result list instead of a profile: open the first result.
        # With a single match Google shows the profile directly but keeps the /maps/search/ URL,
        # so recognise a profile by its tab bar (Overview / Reviews / About), not by the URL alone.
        if "/maps/place/" not in d.current_url and not self._profile_open():
            results = d.find_elements("css selector", "a[href*='/maps/place/']")
            if not results:
                raise ScrapeError("No Google Maps profile found for this competitor")
            results[0].click()
            self._pause(2.0, 3.0)
            for _ in range(10):  # the profile panel loads after the click
                if self._profile_open():
                    break
                time.sleep(0.8)
            self.check_verification()

    def _profile_open(self) -> bool:
        try:
            # A results list also has a heading ("Results"), so require a real business name.
            headings = [h.text.strip().lower() for h in self.driver.find_elements("css selector", "div[role='main'] h1")]
            return bool(self.driver.find_elements("css selector", "div[role='main'] button[role='tab']")) and \
                any(h and h != "results" for h in headings)
        except Exception:
            return False

    def read_header(self, profile: ScrapedProfile):
        d = self.driver
        js = r"""
        const q = s => document.querySelector(s);
        // A search results list keeps its "Results" heading in the DOM next to the opened profile.
        const name = [...document.querySelectorAll('h1')].map(h => (h.innerText || '').trim()).find(t => t && t.toLowerCase() !== 'results') || '';
        const cat = (q('button[jsaction*="category"]') || {}).innerText || '';
        const addr = (q('button[data-item-id="address"]') || {}).getAttribute ? q('button[data-item-id="address"]').getAttribute('aria-label') : '';
        const rate = [...document.querySelectorAll('span[aria-hidden="true"], div[role="img"]')].map(n => n.getAttribute('aria-label') || n.innerText).find(t => /^\d[.,]\d$/.test((t||'').trim())) || '';
        const rev = [...document.querySelectorAll('span[aria-label], button[aria-label]')].map(n => n.getAttribute('aria-label')).find(t => /[\d,]+\s+reviews?/i.test(t||'')) || '';
        return {name, cat, addr, rate, rev};
        """
        try:
            h = d.execute_script(js)
        except Exception:
            return
        profile.name = (h.get("name") or "").strip()
        profile.category = (h.get("cat") or "").strip()
        profile.address = re.sub(r"^Address:\s*", "", (h.get("addr") or "").strip())
        try:
            profile.rating = float((h.get("rate") or "").replace(",", ".")) if h.get("rate") else None
        except ValueError:
            pass
        m = re.search(r"([\d,]+)\s+reviews?", h.get("rev") or "", re.I)
        if m:
            profile.review_count = int(m.group(1).replace(",", ""))
        profile.maps_url = d.current_url

    def open_updates_tab(self) -> bool:
        d = self.driver
        for xp in ("//button[@role='tab'][contains(translate(@aria-label,'UPDATES','updates'),'updates')]",
                   "//button[@role='tab'][.//div[normalize-space()='Updates']]",
                   "//button[@role='tab'][contains(translate(@aria-label,'POSTS','posts'),'posts')]"):
            tabs = d.find_elements("xpath", xp)
            if tabs:
                tabs[0].click()
                self._pause()
                return True
        # Overview shows a "From the owner" preview; its "See local posts" control opens the full list.
        for el in d.find_elements("css selector", "div[role='main'] [aria-label='See local posts']")[:1]:
            try:
                el.click()
                self._pause()
                return True
            except Exception:
                pass
        # Only buttons that are clearly about updates; a bare "next button" can be a photo and opens the viewer.
        for xp in ("//button[contains(@aria-label,'updates') or contains(@aria-label,'Updates')]",
                   "//*[normalize-space()='From the owner']/following::button"
                   "[contains(., 'See all') or contains(., 'updates') or contains(@aria-label, 'pdates')][1]"):
            btns = d.find_elements("xpath", xp)
            if btns:
                try:
                    btns[0].click()
                    self._pause()
                    return True
                except Exception:
                    continue
        return False

    def _scroll_panel(self, rounds=8):
        d = self.driver
        js = """
        const mains = document.querySelectorAll('div[role="main"]');
        const pane = mains[mains.length - 1] || document;
        const feed = [...pane.querySelectorAll('div')].filter(e => e.scrollHeight > e.clientHeight + 50)
                      .sort((a,b) => b.scrollHeight - a.scrollHeight)[0];
        if (!feed) return 0;
        feed.scrollTop = feed.scrollHeight; return feed.scrollHeight;
        """
        last = 0
        for _ in range(rounds):
            try:
                h = d.execute_script(js) or 0
            except Exception:
                break
            self._pause(0.8, 1.6)
            if h == last:
                break
            last = h
        # Expand truncated update text
        for b in d.find_elements("xpath", "//button[normalize-space()='More' or @aria-label='See more']")[:40]:
            try:
                b.click()
            except Exception:
                pass

    def extract_posts(self, business_name: str = ""):
        cards = self.driver.execute_script(EXTRACT_JS) or []
        posts = []
        page = self.driver.current_url
        # Post headers repeat the business name; the post list can replace the h1, so also use the known name.
        names = {e.text.strip().lower() for e in self.driver.find_elements("css selector", "div[role='main'] h1") if e.text.strip()}
        if business_name:
            names.add(business_name.strip().lower())
        for c in cards:
            raw_text, date_label = c.get("text", ""), c.get("date", "")
            cta_label, cta_url, post_url = "", "", c.get("share", "")
            for link in c.get("links", []):
                label = (link.get("label") or "").strip()
                href = link.get("href") or ""
                low = label.lower()
                if "/posts/" in href or "lpu=" in href:
                    post_url = href
                if not cta_label and any(low.startswith(w) for w in CTA_WORDS):
                    cta_label, cta_url = label, href
            raw_text = re.sub(r"[-]", "", raw_text)  # icon-font glyphs
            lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
            drop = {date_label.lower(), cta_label.lower(), "more", "share", "like", "less"} | names
            body = "\n".join(ln for ln in lines if ln.lower() not in drop)
            if len(body) < 15:
                continue
            posts.append({"text": body, "published_raw": date_label, "post_url": post_url,
                          "cta_label": cta_label, "cta_url": cta_url, "images": c.get("images", [])[:6],
                          "source_ref": page})
        return posts

    def scrape(self, name: str, maps_url: str = "", address: str = "") -> ScrapedProfile:
        if not self.driver:
            self.start()
        profile = ScrapedProfile()
        self.open_profile(name, maps_url, address)
        self.read_header(profile)
        if not self.open_updates_tab():
            profile.notes.append("No Updates tab on this profile; read the Overview panel instead")
        self.check_verification()
        self._scroll_panel()
        profile.posts = self.extract_posts(profile.name)
        if not profile.posts:
            profile.notes.append("No Google Maps updates found on the profile")
            if self.limited_view():
                profile.notes.append("Google is showing a limited (signed-out) view of Maps, which hides Updates. "
                                     "Sign in to a Google account in the scraper browser profile, then scrape again.")
        return profile

    def limited_view(self) -> bool:
        try:
            return "limited view of google maps" in self.driver.page_source.lower()
        except Exception:
            return False

    def resume_after_verification(self, name, maps_url="", address="") -> ScrapedProfile:
        """Called after a human solved the challenge in the same browser session."""
        self.check_verification()
        return self.scrape(name, maps_url, address)

    # -------------------------------------------------------------- discovery (bonus)
    def discover(self, keyword: str, limit: int = 15):
        d = self.driver or self.start().driver
        d.get(f"https://www.google.com/maps/search/{quote_plus(keyword)}?hl=en")
        self._pause(2.5, 4.0)
        self._handle_consent()
        self.check_verification()
        self._scroll_panel(rounds=4)
        js = r"""
        return [...document.querySelectorAll('a[href*="/maps/place/"]')].map(a => {
          const card = a.closest('div[jsaction]') || a.parentElement;
          const txt = card ? card.innerText : '';
          const rating = (txt.match(/\b(\d[.,]\d)\b/) || [])[1] || '';
          return {name: a.getAttribute('aria-label') || '', url: a.href, text: txt, rating};
        });
        """
        found, seen = [], set()
        for r in d.execute_script(js) or []:
            if not r.get("name") or r["url"] in seen:
                continue
            seen.add(r["url"])
            lines = [ln for ln in (r.get("text") or "").splitlines() if ln.strip()]
            found.append({"name": r["name"], "maps_url": r["url"],
                          "category": next((ln for ln in lines[1:4] if "·" in ln), "").split("·")[0].strip(),
                          "address": next((ln.split("·")[-1].strip() for ln in lines[1:5] if "·" in ln), ""),
                          "rating": float(r["rating"].replace(",", ".")) if r.get("rating") else None})
            if len(found) >= limit:
                break
        return found


def available() -> tuple:
    """Can a live scrape run on this machine? Returns (ok, reason)."""
    try:
        import selenium  # noqa: F401
    except ImportError:
        return False, "Selenium is not installed"
    kind, _ = find_browser()
    if not kind:
        return False, "No Chrome, Chromium or Edge browser found (set CHROME_BINARY or EDGE_BINARY)"
    return True, f"ready ({'Edge' if kind == 'edge' else 'Chrome'})"
