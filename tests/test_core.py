"""Core tests: fingerprints, duplicate detection, analysis, generation, and the scraper extractor."""
import os
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

os.environ["GMCI_DATA_DIR"] = tempfile.mkdtemp(prefix="gmci-test-")
os.environ["GMCI_SEED_DEMO"] = "0"
os.environ["GMCI_SCHEDULER"] = "0"
# Set to empty rather than removing: config loads .env with setdefault, which would refill removed keys
# and make the tests call real AI providers.
for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "XAI_API_KEY", "OPENROUTER_API_KEY"):
    os.environ[key] = ""

from gmci import generator, repository as repo  # noqa: E402
from gmci.ai.analysis import analyse_project  # noqa: E402
from gmci.db import row, session  # noqa: E402
from gmci.fingerprint import business_key, post_fingerprint  # noqa: E402
from gmci.seed import seed_demo  # noqa: E402
from gmci.textutil import resolve_relative_date  # noqa: E402
from gmci.trends import gap_analysis, topic_trends  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def test_fingerprint_prefers_post_id_and_ignores_cosmetic_text_changes():
    key = business_key("Test Salon", "https://www.google.com/maps/place/Test+Salon/@19,73,17z")
    a, basis = post_fingerprint(key, "x", "https://www.google.com/maps/posts/AbCdEf123456?utm_source=x")
    b, _ = post_fingerprint(key, "different text", "https://www.google.com/maps/posts/AbCdEf123456")
    assert a == b and basis.startswith("post id")
    t1, _ = post_fingerprint(key, "Diwali offer!!  Flat 30% OFF 🎉")
    t2, _ = post_fingerprint(key, "diwali offer flat 30% off")
    assert t1 == t2


def test_business_key_uses_place_identity():
    url = "https://www.google.com/maps/place/X/data=!4m6!3m5!1s0x3be7c1:0xabc123!8m2"
    assert business_key("Anything", url) == "fid:0x3be7c1:0xabc123"
    assert business_key("Glamour Studio", "", "Kharghar") == business_key("glamour  studio", "", "KHARGHAR")


def test_relative_dates():
    assert resolve_relative_date("2 weeks ago") is not None
    assert resolve_relative_date("12 Mar 2026") == "2026-03-12"
    assert resolve_relative_date("") is None


def test_store_post_skips_duplicates_and_shares_competitors_across_projects():
    with session() as conn:
        p1 = repo.create_project(conn, "P1", "salon", "Kharghar")
        p2 = repo.create_project(conn, "P2", "salon", "Vashi")
        b1, created1 = repo.add_competitor(conn, p1, "Shared Salon", "", "Vashi")
        b2, created2 = repo.add_competitor(conn, p2, "Shared Salon", "", "Vashi")
        assert b1 == b2 and created1 and not created2
        post = {"text": "Hair spa at flat 20% off this week", "published_raw": "3 days ago"}
        _, new1 = repo.store_post(conn, b1, post)
        _, new2 = repo.store_post(conn, b1, dict(post, text="Hair spa at flat 20% OFF this week!"))
        assert new1 and not new2
        assert row(conn, "SELECT times_seen FROM posts WHERE business_id=?", (b1,))["times_seen"] == 2


@pytest.fixture(scope="module")
def demo():
    seed_demo(force=True)
    with session() as conn:
        return row(conn, "SELECT id FROM projects WHERE name='ABC Salon'")["id"]


def test_demo_seed_has_analysed_posts_and_trends(demo):
    with session() as conn:
        t = topic_trends(conn, demo)
        assert t["total_competitors"] == 8 and t["total_posts"] > 60
        top = t["rows"][0]
        assert 0 < top["competitors_using"] <= 8 and top["competitor_pct"] == round(100 * top["competitors_using"] / 8)
        gaps = gap_analysis(conn, demo)
        assert gaps["has_own"] and gaps["missing"] and gaps["recommendations"]


def test_reanalysis_is_idempotent(demo):
    with session() as conn:
        res = analyse_project(conn, demo, preferred="offline")
        assert res["analysed"] == 0


def test_generator_honours_count_and_never_repeats(demo):
    with session() as conn:
        first = generator.generate(conn, demo, 7, "idea", preferred="offline")
        second = generator.generate(conn, demo, 7, "idea", preferred="offline")
        assert first["generated"] == 7 and second["generated"] == 7
        titles = [r["title"] for r in conn.execute("SELECT title FROM ideas WHERE project_id=?", (demo,))]
        assert len(titles) == len(set(titles))
        hist = generator.History(conn, demo)
        last = conn.execute("SELECT topic, title FROM ideas WHERE project_id=? ORDER BY id DESC LIMIT 1", (demo,)).fetchone()
        assert hist.is_duplicate(last["topic"], last["title"])


def test_complete_update_has_all_parts(demo):
    with session() as conn:
        res = generator.generate(conn, demo, 1, "update", preferred="offline", make_images=True)
        idea = row(conn, "SELECT * FROM ideas WHERE id=?", (res["ids"][0],))
        assert idea["body"] and len(idea["body"]) <= 1500
        assert idea["cta"] and idea["image_concept"] and idea["image_path"] and idea["keywords"] != "[]"
        assert idea["similarity"] is not None


def test_demo_scrape_second_run_adds_fresh_posts_then_only_duplicates(demo):
    from gmci.jobs import manager
    with session() as conn:
        ids = repo.project_business_ids(conn, demo)[:3]

    def run():
        rid = manager.start_scrape(demo, ids, "demo")
        for _ in range(120):
            with session() as conn:
                r = row(conn, "SELECT * FROM scrape_runs WHERE id=?", (rid,))
            if r["status"] in ("done", "failed"):
                return r
            time.sleep(0.25)
        raise AssertionError("run did not finish")

    first = run()
    assert first["status"] == "done" and first["new_posts"] >= 3 and first["duplicates"] > 0
    runs = [run() for _ in range(3)]
    assert runs[-1]["new_posts"] == 0 and runs[-1]["duplicates"] == runs[-1]["posts_found"]


def _chrome_ok():
    from gmci.scraper.selenium_maps import available
    return available()[0] and bool(os.environ.get("CHROMEDRIVER_PATH") or os.environ.get("RUN_SELENIUM_TESTS"))


@pytest.fixture(scope="module")
def fixture_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(FIXTURES))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.mark.skipif(not _chrome_ok(), reason="set CHROMEDRIVER_PATH or RUN_SELENIUM_TESTS=1 to run browser tests")
def test_selenium_extracts_updates_from_maps_like_page(fixture_server):
    from gmci.scraper.selenium_maps import MapsScraper
    s = MapsScraper(headless=True, log=lambda *_: None)
    s._pause = lambda *a, **k: time.sleep(0.2)
    s.start()
    try:
        s.driver.get(fixture_server + "/maps_profile.html")
        profile = __import__("gmci.scraper", fromlist=["ScrapedProfile"]).ScrapedProfile()
        s.read_header(profile)
        assert profile.name == "Test Salon Kharghar" and profile.rating == 4.6 and profile.review_count == 1234
        assert s.open_updates_tab()
        posts = s.extract_posts()
        texts = [p["text"] for p in posts]
        assert len(posts) == 3, texts                      # the review is not mistaken for an update
        diwali = next(p for p in posts if "Diwali" in p["text"])
        assert diwali["published_raw"] == "2 weeks ago" and diwali["post_url"].endswith("AbCdEf123456")
        assert diwali["cta_label"] == "Learn more" and diwali["images"]
        monsoon = next(p for p in posts if "Monsoon" in p["text"])
        assert monsoon["cta_label"] == "Book" and monsoon["images"]
    finally:
        s.stop()


@pytest.mark.skipif(not _chrome_ok(), reason="set CHROMEDRIVER_PATH or RUN_SELENIUM_TESTS=1 to run browser tests")
def test_selenium_detects_captcha(fixture_server):
    from gmci.scraper import VerificationRequired
    from gmci.scraper.selenium_maps import MapsScraper
    s = MapsScraper(headless=True, log=lambda *_: None).start()
    try:
        s.driver.get(fixture_server + "/sorry.html")
        with pytest.raises(VerificationRequired) as exc:
            s.check_verification()
        assert exc.value.screenshot and Path(exc.value.screenshot).exists()
    finally:
        s.stop()
