"""Stable identities for businesses and posts.

Post fingerprint strategy, strongest signal first:
1. A Google post id found in the post URL (``/posts/<id>`` or ``lpu=`` / ``postid=`` parameters).
2. The full post URL (normalised, tracking parameters removed).
3. Business identity + normalised text (first 400 chars). Dates are left out on purpose: Maps
   shows relative dates ("3 weeks ago") that resolve differently on each re-scrape.

The basis used is stored next to the hash so the repository can show *why* two posts were
considered the same. Whitespace, emoji, case and URL differences in the text do not change (3).
"""
import hashlib
import re
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from .textutil import normalise

_CID = re.compile(r"[?&]cid=(\d+)")
_PLACE_ID = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.I)
_CHIJ = re.compile(r"(ChIJ[\w-]{10,})")
_POST_ID = re.compile(r"/posts/([\w-]{6,})|[?&](?:lpu|postid|post_id)=([\w-]{6,})", re.I)
_TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "hl", "gl", "entry", "g_ep"}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def business_key(name: str, maps_url: str = "", address: str = "") -> str:
    """Identity for a Google Maps profile, used to avoid duplicate competitors."""
    url = unquote(maps_url or "")
    for pattern, prefix in ((_PLACE_ID, "fid"), (_CHIJ, "pid"), (_CID, "cid")):
        m = pattern.search(url)
        if m:
            return f"{prefix}:{m.group(1).lower()}"
    m = re.search(r"/maps/place/([^/@]+)", url)
    if m:
        return "place:" + normalise(m.group(1).replace("+", " "))
    return "name:" + normalise(f"{name} {address}")


def clean_url(url: str) -> str:
    if not url:
        return ""
    parts = urlparse(url.strip())
    query = {k: v for k, v in parse_qs(parts.query).items() if k.lower() not in _TRACKING}
    return urlunparse(parts._replace(query=urlencode(query, doseq=True), fragment=""))


def post_fingerprint(business_key_value: str, text: str, post_url: str = "", published_at: str = "") -> tuple:
    """Return ``(fingerprint, basis)`` for a scraped post."""
    if post_url:
        m = _POST_ID.search(post_url)
        if m:
            pid = m.group(1) or m.group(2)
            return _sha(f"postid:{pid}"), f"post id {pid}"
        cleaned = clean_url(post_url)
        if "/maps/place/" not in cleaned:  # a profile URL is not specific to one post
            return _sha(f"url:{cleaned}"), "post URL"
    body = normalise(text)[:400]
    return _sha(f"text:{business_key_value}|{body}"), "business + normalised text"
