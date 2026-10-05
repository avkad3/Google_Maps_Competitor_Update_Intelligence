"""Demo scrape source with the same interface as ``MapsScraper``.

It lets an evaluator run the full scraping workflow (progress, duplicate skipping, new posts,
CAPTCHA pause/continue) without depending on Google. Every competitor "has" a fixed set of posts
(the ones seeded into the repository) plus one or two fresh posts that are released one per
scrape, so the second scrape shows new posts and every later scrape shows only duplicates.
"""
import time

from .. import images
from ..db import row, session
from ..seed import DEMO_TAG, competitor_posts, find_demo_profile, fresh_posts
from . import ScrapedProfile, VerificationRequired


class DemoScraper:
    def __init__(self, simulate_captcha=False, log=print, delay=1.2, **_):
        self.simulate_captcha = simulate_captcha
        self.log = log
        self.delay = delay
        self.challenged = False
        self.driver = None

    def start(self):
        return self

    def stop(self):
        pass

    def scrape(self, name, maps_url="", address="", business_id=None, own_templates=False) -> ScrapedProfile:
        time.sleep(self.delay)
        if self.simulate_captcha and not self.challenged:
            self.challenged = True
            shot = images.svg_card("screenshots", f"demo-captcha-{int(time.time())}", "Verify you're not a robot",
                                   "Simulated Google 'unusual traffic' page (demo mode)", "Demo CAPTCHA", badge="CAPTCHA")
            raise VerificationRequired("Simulated CAPTCHA: Google asked to verify this session (demo mode)",
                                       "https://www.google.com/sorry/index (simulated)", shot)
        templates, fresh, area, seed_key = find_demo_profile(name)
        is_own = False
        with session() as conn:
            if business_id:
                is_own = bool(row(conn, "SELECT 1 FROM projects WHERE own_business_id=?", (business_id,)))
            done_runs = row(conn, """SELECT COUNT(*) AS n FROM scrape_run_items i JOIN scrape_runs r ON r.id = i.run_id
                                     WHERE i.business_id = ? AND r.mode = 'demo' AND r.trigger != 'seed'
                                     AND i.status = 'done'""", (business_id,))["n"] if business_id else 0
        if is_own and seed_key != "custom":
            posts = []  # own profile: return the seeded posts again (all duplicates)
            from ..demo_data import PROJECTS
            from ..seed import _make_post, _rng
            from datetime import date
            for proj in PROJECTS:
                if proj["name"] == seed_key:
                    posts = [_make_post(proj["posts"][i], name, area, _rng("own", name, i), date.today(),
                                        "demo/own", f"o{i}") for i in proj["own_templates"]]
        else:
            posts = competitor_posts(templates, name, area, seed_key)
            extra = fresh_posts(fresh, name, area) if fresh else []
            posts += extra[:done_runs + 1]
        profile = ScrapedProfile(name=name, maps_url=maps_url, address=address, posts=posts)
        profile.notes.append(f"Source: {DEMO_TAG}")
        return profile

    def resume_after_verification(self, name, maps_url="", address="", **kw):
        return self.scrape(name, maps_url, address, **kw)

    def discover(self, keyword, limit=15, project_name=""):
        from ..demo_data import PROJECTS
        found = []
        for proj in PROJECTS:
            for name, address, category, rating, kw in proj["discoverable"]:
                if kw.lower() == keyword.lower() or keyword.lower() in kw.lower():
                    from ..seed import maps_search_url
                    found.append({"name": name, "address": address, "category": category, "rating": rating,
                                  "maps_url": maps_search_url(name, address)})
        if not found:
            area = keyword.split(" in ")[-1].title() if " in " in keyword else "Nearby"
            kind = keyword.split(" in ")[0].title() if " in " in keyword else keyword.title()
            for i, prefix in enumerate(("Royal", "Prime", "Elite", "City")):
                from ..seed import maps_search_url
                name = f"{prefix} {kind} {area}"
                found.append({"name": name, "address": area, "category": kind, "rating": round(4.0 + i * 0.2, 1),
                              "maps_url": maps_search_url(name, area)})
        time.sleep(self.delay)
        return found[:limit]
