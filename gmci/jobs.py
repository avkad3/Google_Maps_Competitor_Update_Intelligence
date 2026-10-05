"""Background scrape / discovery jobs, CAPTCHA pause-and-continue, and scheduled re-scrapes.

One scrape runs at a time (a single browser, competitors processed one by one). When Google
challenges the session the job is paused, the run and the competitor are marked
``needs_verification``, and the web UI shows a banner with a screenshot plus Continue / Skip /
Cancel buttons. Nothing fails silently: every outcome is written to ``scrape_run_items``.
"""
import random
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import config
from .ai.analysis import analyse_project
from .db import now, row, rows, session
from .images import download
from .repository import add_media, store_post, upsert_business
from .fingerprint import business_key
from .scraper import ScrapeError, VerificationRequired

VERIFY_TIMEOUT = 30 * 60


def live_available():
    from .scraper.selenium_maps import available
    return available()


class Job:
    def __init__(self, run_id, project_id, business_ids, mode, simulate_captcha):
        self.run_id = run_id
        self.project_id = project_id
        self.business_ids = business_ids
        self.mode = mode
        self.simulate_captcha = simulate_captcha
        self.action = None
        self.event = threading.Event()
        self.cancelled = False
        self.scraper = None
        self.log_lines = []
        self.driver_lock = threading.Lock()

    def log(self, msg):
        self.log_lines.append(f"{datetime.now().strftime('%H:%M:%S')} {msg}")
        self.log_lines = self.log_lines[-200:]


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.run_lock = threading.Lock()  # one browser session at a time
        self._scheduler = None

    # ------------------------------------------------------------ scrape
    def start_scrape(self, project_id, business_ids, mode="demo", simulate_captcha=False, trigger="manual"):
        with session() as conn:
            run_id = conn.execute(
                """INSERT INTO scrape_runs (project_id, mode, trigger, status, message, competitors_total)
                   VALUES (?, ?, ?, 'queued', 'Waiting for the scraper', ?)""",
                (project_id, mode, trigger, len(business_ids))).lastrowid
            for bid in business_ids:
                b = row(conn, "SELECT name FROM businesses WHERE id=?", (bid,))
                conn.execute("INSERT INTO scrape_run_items (run_id, business_id, business_name, status) VALUES (?, ?, ?, 'pending')",
                             (run_id, bid, b["name"] if b else "?"))
        job = Job(run_id, project_id, business_ids, mode, simulate_captcha)
        self.jobs[run_id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"scrape-{run_id}").start()
        return run_id

    def act(self, run_id, action):
        """User response to a verification pause: continue | skip | cancel."""
        job = self.jobs.get(run_id)
        if not job:
            return False
        if action == "cancel":
            job.cancelled = True
        job.action = action
        job.event.set()
        return True

    def _update_run(self, run_id, **fields):
        with session() as conn:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE scrape_runs SET {sets} WHERE id=?", list(fields.values()) + [run_id])

    def _update_item(self, item_id, **fields):
        with session() as conn:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE scrape_run_items SET {sets} WHERE id=?", list(fields.values()) + [item_id])

    def _make_scraper(self, job):
        if job.mode == "live":
            from .scraper.selenium_maps import MapsScraper
            return MapsScraper(log=job.log, screenshot_prefix=f"run{job.run_id}")
        from .scraper.demo_source import DemoScraper
        return DemoScraper(simulate_captcha=job.simulate_captcha, log=job.log)

    def _run(self, job):
        with self.run_lock:
            self._update_run(job.run_id, status="running", started_at=now(), message="Scraping competitors one by one")
            try:
                job.scraper = self._make_scraper(job).start()
            except Exception as exc:
                self._finish_failed(job, f"Could not start the scraper: {exc}")
                return
            try:
                with session() as conn:
                    items = rows(conn, "SELECT * FROM scrape_run_items WHERE run_id=? ORDER BY id", (job.run_id,))
                for idx, item in enumerate(items):
                    if job.cancelled:
                        self._update_item(item["id"], status="skipped", error="Run cancelled by user")
                        continue
                    self._scrape_one(job, item)
                    self._refresh_totals(job.run_id)
                    if job.mode == "live" and idx < len(items) - 1:
                        time.sleep(random.uniform(4, 9))  # polite pacing between profiles
            finally:
                if job.scraper:
                    job.scraper.stop()
            totals = self._refresh_totals(job.run_id)
            if job.cancelled:
                self._update_run(job.run_id, status="cancelled", ended_at=now(), message="Cancelled by user")
                return
            msg = f"{totals['new_posts']} new posts, {totals['duplicates']} duplicates skipped"
            if totals["new_posts"]:
                self._update_run(job.run_id, message=msg + "; analysing new posts")
                try:
                    with session() as conn:
                        analyse_project(conn, job.project_id)
                    msg += "; analysed"
                except Exception as exc:
                    msg += f" (analysis failed: {exc})"
                msg += self._auto_generate(job, msg)
            status = "failed" if totals["failures"] and totals["failures"] == totals["competitors_total"] else "done"
            self._update_run(job.run_id, status=status, ended_at=now(), message=msg)

    def _auto_generate(self, job, msg) -> str:
        """After new posts are analysed, write fresh content from them (GMCI_AUTO_IDEAS / GMCI_AUTO_UPDATES, 0 = off)."""
        from . import generator
        parts = []
        for kind, var, default in (("idea", "GMCI_AUTO_IDEAS", 5), ("update", "GMCI_AUTO_UPDATES", 2)):
            try:
                count = int(config.env(var, str(default)) or 0)
            except ValueError:
                count = default
            if count <= 0:
                continue
            self._update_run(job.run_id, message=f"{msg}; generating {kind}s")
            job.log(f"Generating {count} {kind}s from the new posts")
            try:
                with session() as conn:
                    res = generator.generate(conn, job.project_id, count, kind, make_images=(kind == "update"))
                parts.append(f"{res['generated']} {'ideas' if kind == 'idea' else 'complete updates'}")
                job.log(f"Generated {res['generated']} {kind}s with {', '.join(res['providers']) or '-'}")
            except Exception as exc:
                job.log(f"{kind} generation failed: {exc}")
                parts.append(f"{kind} generation failed")
        return f"; generated {' and '.join(parts)}" if parts else ""

    def _finish_failed(self, job, message):
        with session() as conn:
            conn.execute("UPDATE scrape_run_items SET status='failed', error=? WHERE run_id=? AND status='pending'",
                         (message, job.run_id))
        self._refresh_totals(job.run_id)
        self._update_run(job.run_id, status="failed", ended_at=now(), message=message)

    def _scrape_one(self, job, item):
        with session() as conn:
            biz = row(conn, "SELECT * FROM businesses WHERE id=?", (item["business_id"],))
        if not biz:
            self._update_item(item["id"], status="failed", error="Competitor was removed")
            return
        self._update_item(item["id"], status="running", started_at=now())
        self._update_run(job.run_id, status="running", message=f"Scraping {biz['name']}")
        job.log(f"Scraping {biz['name']}")
        kwargs = {"business_id": biz["id"]} if job.mode == "demo" else {}
        attempts, interventions = 0, []
        profile = None
        while True:
            attempts += 1
            try:
                with job.driver_lock:
                    if attempts == 1:
                        profile = job.scraper.scrape(biz["name"], biz["maps_url"] or "", biz["address"] or "", **kwargs)
                    else:
                        profile = job.scraper.resume_after_verification(biz["name"], biz["maps_url"] or "",
                                                                        biz["address"] or "", **kwargs)
                break
            except VerificationRequired as v:
                job.log(f"Verification required: {v.reason}")
                interventions.append(v.reason)
                self._update_item(item["id"], status="needs_verification", captcha_required=1, screenshot=v.screenshot,
                                  manual_intervention="Waiting for manual verification", error=v.reason)
                self._update_run(job.run_id, status="needs_verification",
                                 message=f"Manual verification needed for {biz['name']}: {v.reason}")
                with session() as conn:
                    conn.execute("UPDATE scrape_runs SET captcha_events = captcha_events + 1 WHERE id=?", (job.run_id,))
                job.event.clear()
                job.action = None
                answered = job.event.wait(VERIFY_TIMEOUT)
                action = job.action if answered else "timeout"
                if action == "continue" and attempts < 4:
                    interventions.append("user completed verification and continued")
                    self._update_run(job.run_id, status="running", message=f"Resuming {biz['name']} after verification")
                    self._update_item(item["id"], status="running", manual_intervention="; ".join(interventions))
                    continue
                reason = {"skip": "skipped by user after verification prompt", "cancel": "run cancelled by user",
                          "timeout": "no response to verification prompt within 30 minutes"}.get(action, "too many verification prompts")
                interventions.append(reason)
                self._update_item(item["id"], status="skipped" if action in ("skip", "cancel") else "failed",
                                  ended_at=now(), manual_intervention="; ".join(interventions), error=v.reason)
                self._update_run(job.run_id, status="running")
                return
            except (ScrapeError, Exception) as exc:
                err = str(exc).splitlines()[0][:300] if str(exc) else type(exc).__name__
                job.log(f"Failed: {err}")
                shot = job.scraper.screenshot("error") if hasattr(job.scraper, "screenshot") and job.mode == "live" else ""
                if not isinstance(exc, ScrapeError):
                    traceback.print_exc()
                self._update_item(item["id"], status="failed", ended_at=now(), error=err, screenshot=shot,
                                  manual_intervention="; ".join(interventions) or None)
                return
        new = dupes = imgs = 0
        with session() as conn:
            if profile.name or profile.rating:
                conn.execute("""UPDATE businesses SET rating=COALESCE(?, rating), review_count=COALESCE(?, review_count),
                                category=COALESCE(NULLIF(?, ''), category), address=COALESCE(NULLIF(?, ''), address),
                                updated_at=? WHERE id=?""",
                             (profile.rating, profile.review_count, profile.category, profile.address, now(), biz["id"]))
            for p in profile.posts:
                post_id, is_new = store_post(conn, biz["id"], p, job.run_id)
                if not is_new:
                    dupes += 1
                    continue
                new += 1
                for i, path in enumerate(p.get("local_images", [])):
                    add_media(conn, post_id, "demo://" + path.split("/media/")[-1], path)
                    imgs += 1
                for i, url in enumerate(p.get("images", [])):
                    local = download(url, f"b{biz['id']}", f"post{post_id}-{i}")
                    add_media(conn, post_id, url, local)
                    imgs += 1 if local else 0
        notes = "; ".join(profile.notes)
        self._update_item(item["id"], status="done", ended_at=now(), posts_found=len(profile.posts), new_posts=new,
                          duplicates=dupes, images_downloaded=imgs,
                          manual_intervention="; ".join(interventions) or None, error=notes or None)
        job.log(f"{biz['name']}: {len(profile.posts)} found, {new} new, {dupes} duplicates")
        for note in profile.notes:
            job.log(f"  note: {note}")

    def _refresh_totals(self, run_id):
        with session() as conn:
            t = row(conn, """SELECT COUNT(*) AS total, SUM(status IN ('done','failed','skipped')) AS done,
                    COALESCE(SUM(posts_found),0) AS found, COALESCE(SUM(new_posts),0) AS new,
                    COALESCE(SUM(duplicates),0) AS dupes, COALESCE(SUM(images_downloaded),0) AS imgs,
                    COALESCE(SUM(status='failed'),0) AS failures FROM scrape_run_items WHERE run_id=?""", (run_id,))
            conn.execute("""UPDATE scrape_runs SET competitors_done=?, posts_found=?, new_posts=?, duplicates=?,
                            images_downloaded=?, failures=? WHERE id=?""",
                         (t["done"] or 0, t["found"], t["new"], t["dupes"], t["imgs"], t["failures"], run_id))
            return row(conn, "SELECT * FROM scrape_runs WHERE id=?", (run_id,))

    # ------------------------------------------------------------ verification console (live mode)
    def console(self, run_id, op, **kw):
        job = self.jobs.get(run_id)
        if not job or job.mode != "live" or not job.scraper or not job.scraper.driver:
            return {"ok": False, "message": "No live browser session for this run"}
        with job.driver_lock if op != "screenshot" else _null():
            if op == "click":
                w, h = job.scraper.viewport()
                job.scraper.click_at(int(kw["x"] * w), int(kw["y"] * h))
            elif op == "type":
                job.scraper.type_text(kw.get("text", ""), kw.get("enter", False))
            time.sleep(0.8)
            path = job.scraper.screenshot("console")
        self._update_items_screenshot(run_id, path)
        return {"ok": True, "screenshot": path}

    def _update_items_screenshot(self, run_id, path):
        with session() as conn:
            conn.execute("UPDATE scrape_run_items SET screenshot=? WHERE run_id=? AND status='needs_verification'",
                         (path, run_id))

    # ------------------------------------------------------------ discovery (bonus)
    def start_discovery(self, project_id, keywords, mode="demo"):
        threading.Thread(target=self._discover, args=(project_id, keywords, mode), daemon=True).start()

    def _discover(self, project_id, keywords, mode):
        if mode == "live":
            from .scraper.selenium_maps import MapsScraper
            scraper = MapsScraper()
        else:
            from .scraper.demo_source import DemoScraper
            scraper = DemoScraper(delay=0.3)
        with self.run_lock:
            try:
                scraper.start()
                for kw in keywords:
                    try:
                        found = scraper.discover(kw)
                    except VerificationRequired as v:
                        self._record_discovery_error(project_id, kw, f"Verification required: {v.reason}")
                        break
                    except Exception as exc:
                        self._record_discovery_error(project_id, kw, f"Discovery failed: {exc}")
                        continue
                    self._store_discovered(project_id, kw, found)
            finally:
                scraper.stop()

    def _record_discovery_error(self, project_id, keyword, message):
        with session() as conn:
            conn.execute("""INSERT OR REPLACE INTO discovered_businesses (project_id, keyword, name, url_key, status, discovered_at)
                            VALUES (?, ?, ?, ?, 'error', ?)""", (project_id, keyword, message, f"error:{keyword}", now()))

    def _store_discovered(self, project_id, keyword, found):
        from .textutil import jaccard, tokens
        with session() as conn:
            existing = rows(conn, "SELECT id, name, url_key FROM businesses")
            linked = {r["business_id"] for r in rows(conn, "SELECT business_id FROM project_competitors WHERE project_id=?", (project_id,))}
            for f in found:
                key = business_key(f["name"], f.get("maps_url", ""), f.get("address", ""))
                match = next((e for e in existing if e["url_key"] == key), None) or \
                    next((e for e in existing if jaccard(tokens(e["name"]), tokens(f["name"])) >= 0.8), None)
                status = "existing" if match and match["id"] in linked else "new"
                conn.execute(
                    """INSERT INTO discovered_businesses (project_id, keyword, name, maps_url, url_key, address, category,
                           rating, existing_business_id, status, discovered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(project_id, url_key) DO UPDATE SET keyword=excluded.keyword, rating=excluded.rating,
                           existing_business_id=excluded.existing_business_id,
                           status=CASE WHEN discovered_businesses.status IN ('added','ignored') THEN discovered_businesses.status
                                       ELSE excluded.status END""",
                    (project_id, keyword, f["name"], f.get("maps_url", ""), key, f.get("address", ""), f.get("category", ""),
                     f.get("rating"), match["id"] if match else None, status, now()))
            conn.execute("DELETE FROM discovered_businesses WHERE project_id=? AND keyword=? AND status='error'",
                         (project_id, keyword))

    # ------------------------------------------------------------ scheduled scraping (bonus)
    def start_scheduler(self, interval=300):
        if self._scheduler:
            return
        self._scheduler = threading.Thread(target=self._schedule_loop, args=(interval,), daemon=True, name="scheduler")
        self._scheduler.start()

    def _schedule_loop(self, interval):
        while True:
            try:
                self.run_due_schedules()
            except Exception:
                traceback.print_exc()
            time.sleep(interval)

    def run_due_schedules(self):
        started = []
        mode = config.env("GMCI_SCHEDULE_MODE", "live" if live_available()[0] else "demo")
        with session() as conn:
            due = rows(conn, "SELECT * FROM projects WHERE schedule_hours > 0")
        for p in due:
            last = p["last_scheduled_at"]
            if last and datetime.fromisoformat(last) > datetime.now(timezone.utc) - timedelta(hours=p["schedule_hours"]):
                continue
            with session() as conn:
                ids = [r["business_id"] for r in rows(conn, "SELECT business_id FROM project_competitors WHERE project_id=?", (p["id"],))]
                conn.execute("UPDATE projects SET last_scheduled_at=? WHERE id=?", (now(), p["id"]))
            if ids:
                started.append(self.start_scrape(p["id"], ids, mode, trigger="schedule"))
        return started


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


manager = JobManager()
