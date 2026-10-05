"""Scraping engine: a live Selenium scraper for Google Maps and a demo source with the same interface."""
from dataclasses import dataclass, field


class VerificationRequired(Exception):
    """Google showed a CAPTCHA / verification / unusual-traffic page. A human must step in."""

    def __init__(self, reason: str, url: str = "", screenshot: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.url = url
        self.screenshot = screenshot


class ScrapeError(Exception):
    pass


@dataclass
class ScrapedProfile:
    name: str = ""
    maps_url: str = ""
    address: str = ""
    category: str = ""
    rating: float | None = None
    review_count: int | None = None
    posts: list = field(default_factory=list)   # dicts: text, published_raw, published_at, post_url, cta_label, cta_url, images, source_ref
    notes: list = field(default_factory=list)   # non-fatal observations, written to the run log
