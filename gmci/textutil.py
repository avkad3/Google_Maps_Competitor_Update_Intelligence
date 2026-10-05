"""Small, dependency-free text helpers: normalisation, tokens, similarity, relative dates."""
import math
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone

STOPWORDS = set("""
a an the and or but if then so of to in on at for from by with without into onto over under up down out
is are was were be been being am do does did doing have has had having it its this that these those there
here we our ours you your yours they them their he she his her i me my mine us not no yes can will just
than too very more most less much many any all each every some such only own same other new now get got
also as about after before again off once what which who whom when where why how let lets lets' s t
book visit call today us now w/ & + - our your
""".split())

_WORD = re.compile(r"[a-z0-9][a-z0-9'&+-]*")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str, keep_stopwords: bool = False) -> list:
    words = _WORD.findall(normalise(text))
    if keep_stopwords:
        return words
    return [w for w in words if w not in STOPWORDS and len(w) > 2 and not w.isdigit()]


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cosine(a_tokens, b_tokens) -> float:
    a, b = Counter(a_tokens), Counter(b_tokens)
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b[t] for t in a.keys() & b.keys())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def ngrams(words, n=2):
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


_REL = re.compile(r"(a|an|one|\d+)\s+(minute|hour|day|week|month|year)s?\s+ago", re.I)


def resolve_relative_date(raw: str, reference: datetime | None = None) -> str | None:
    """Turn Google's "3 weeks ago" / "a month ago" / "12 Mar 2026" into an ISO date (approximate)."""
    if not raw:
        return None
    reference = reference or datetime.now(timezone.utc)
    raw = raw.strip()
    m = _REL.search(raw)
    if m:
        qty = 1 if m.group(1).lower() in {"a", "an", "one"} else int(m.group(1))
        unit = m.group(2).lower()
        delta = {
            "minute": timedelta(minutes=qty), "hour": timedelta(hours=qty), "day": timedelta(days=qty),
            "week": timedelta(weeks=qty), "month": timedelta(days=30 * qty), "year": timedelta(days=365 * qty),
        }[unit]
        return (reference - delta).date().isoformat()
    if raw.lower() in {"today", "just now"}:
        return reference.date().isoformat()
    if raw.lower() == "yesterday":
        return (reference - timedelta(days=1)).date().isoformat()
    for fmt in ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y", "%d %B %Y", "%B %d, %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def iso_date(value) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return (value or "")[:10]
