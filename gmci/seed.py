"""Builds the pre-populated demo repository (and powers the demo scrape source)."""
import hashlib
import random
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

from . import images
from .ai.analysis import analyse_project
from .db import now, row, session
from .demo_data import PROJECTS, SALON_FRESH, SALON_POSTS
from .repository import add_competitor, add_media, create_project, set_keywords, store_post

DEMO_TAG = "demo dataset (synthetic, fictional businesses)"


def maps_search_url(name, address):
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(name + ' ' + address)}"


def _rng(*parts):
    return random.Random(int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest(), 16))


def _relative(d: date, today: date) -> str:
    days = (today - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        w = days // 7
        return "a week ago" if w == 1 else f"{w} weeks ago"
    if days < 365:
        m = days // 30
        return "a month ago" if m == 1 else f"{m} months ago"
    return "a year ago"


def _date_for(month_hint: int, rnd, today: date, window=330) -> date:
    if month_hint:
        year = today.year if month_hint <= today.month else today.year - 1
        d = date(year, month_hint, rnd.randint(1, 26))
        return min(d, today)
    return today - timedelta(days=rnd.randint(3, window))


def _make_post(tpl, name, area, rnd, today, folder, key):
    headline, cta, month, text = tpl
    d = _date_for(month, rnd, today)
    body = text.format(biz=name, area=area)
    n_images = 2 if any(w in headline.lower() for w in ("before", "transformation", "makeover", "bob")) else \
        (0 if rnd.random() < 0.15 else 1)
    imgs = [images.svg_card(folder, f"{key}-{i}", headline, f"{name} · {area}", "Google Maps update · demo image",
                            badge=["Before", "After"][i] if n_images == 2 else "")
            for i in range(n_images)]
    return {"text": body, "published_at": d.isoformat(), "published_raw": _relative(d, today),
            "cta_label": cta, "cta_url": maps_search_url(name, area) if cta != "Call now" else "tel:",
            "source_ref": DEMO_TAG, "local_images": imgs, "headline": headline}


def competitor_posts(templates, name, area, seed_key, count_range=(8, 12)):
    """Deterministic set of posts a demo competitor 'has published'."""
    rnd = _rng("posts", seed_key, name)
    n = rnd.randint(*count_range)
    picks = rnd.sample(range(len(templates)), min(n, len(templates)))
    today = date.today()
    folder = "demo/" + hashlib.md5(name.encode()).hexdigest()[:8]
    return [_make_post(templates[i], name, area, _rng("date", name, i), today, folder, f"p{i}") for i in picks]


def fresh_posts(fresh_templates, name, area):
    """Posts the demo source releases on later scrapes (one per run)."""
    rnd = _rng("fresh", name)
    picks = rnd.sample(range(len(fresh_templates)), rnd.choice([1, 2, 2]))
    today = date.today()
    folder = "demo/" + hashlib.md5(name.encode()).hexdigest()[:8]
    out = []
    for k, i in enumerate(picks):
        p = _make_post(fresh_templates[i], name, area, _rng("fdate", name, i), today, folder, f"f{i}")
        d = today - timedelta(days=k + 1)
        p["published_at"], p["published_raw"] = d.isoformat(), _relative(d, today)
        out.append(p)
    return out


def find_demo_profile(name: str):
    """Look a business up in the demo catalogue: returns (templates, fresh, area, seed_key)."""
    for proj in PROJECTS:
        for cname, address, area, _cat in proj["competitors"]:
            if cname.lower() == name.lower():
                return proj["posts"], proj["fresh"], area, proj["name"]
        if proj["own"][0].lower() == name.lower():
            return [proj["posts"][i] for i in proj["own_templates"]], [], proj["location"].split(",")[0], proj["name"]
    # Unknown business added by the user while in demo mode: plausible salon-style posts.
    return SALON_POSTS, SALON_FRESH, "your area", "custom"


def seed_demo(force=False):
    with session() as conn:
        if not force and row(conn, "SELECT id FROM projects LIMIT 1"):
            return False
    today = date.today()
    for proj in PROJECTS:
        with session() as conn:
            own_name, own_addr = proj["own"]
            pid = create_project(conn, proj["name"], proj["industry"], proj["location"], own_name,
                                 maps_search_url(own_name, own_addr), own_addr)
            set_keywords(conn, pid, proj["keywords"])
            started = datetime.now(timezone.utc) - timedelta(days=6, hours=3)
            run_id = conn.execute(
                """INSERT INTO scrape_runs (project_id, mode, trigger, status, message, started_at, competitors_total)
                   VALUES (?, 'demo', 'seed', 'running', 'Initial collection (demo dataset)', ?, ?)""",
                (pid, started.replace(microsecond=0).isoformat(), len(proj["competitors"]) + 1)).lastrowid
            totals = dict(found=0, new=0, imgs=0)
            t = started
            targets = [(own_name, own_addr, proj["location"].split(",")[0], "own")] + \
                      [(c[0], c[1], c[2], c[3]) for c in proj["competitors"]]
            for idx, (name, address, area, cat) in enumerate(targets):
                if cat == "own":
                    bid = row(conn, "SELECT own_business_id AS id FROM projects WHERE id=?", (pid,))["id"]
                    posts = [_make_post(proj["posts"][i], name, area, _rng("own", name, i), today,
                                        "demo/own" + str(pid), f"o{i}") for i in proj["own_templates"]]
                else:
                    bid, _ = add_competitor(conn, pid, name, maps_search_url(name, address), address, cat)
                    rnd = _rng("meta", name)
                    conn.execute("UPDATE businesses SET rating=?, review_count=? WHERE id=?",
                                 (round(rnd.uniform(4.0, 4.9), 1), rnd.randint(80, 1400), bid))
                    posts = competitor_posts(proj["posts"], name, area, proj["name"])
                item_start = t
                new = imgs = 0
                for p in posts:
                    post_id, is_new = store_post(conn, bid, p, run_id)
                    if is_new:
                        new += 1
                        for path in p["local_images"]:
                            add_media(conn, post_id, "demo://" + path.split("/media/")[-1], path)
                            imgs += 1
                t = t + timedelta(seconds=random.Random(idx).randint(25, 70))
                conn.execute(
                    """INSERT INTO scrape_run_items (run_id, business_id, business_name, status, started_at, ended_at,
                           posts_found, new_posts, duplicates, images_downloaded, captcha_required, manual_intervention)
                       VALUES (?, ?, ?, 'done', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (run_id, bid, name, item_start.replace(microsecond=0).isoformat(), t.replace(microsecond=0).isoformat(),
                     len(posts), new, len(posts) - new, imgs, 1 if idx == 3 else 0,
                     "Verification page shown; user completed it and resumed the job" if idx == 3 else None))
                totals["found"] += len(posts)
                totals["new"] += new
                totals["imgs"] += imgs
            conn.execute(
                """UPDATE scrape_runs SET status='done', ended_at=?, competitors_done=competitors_total, posts_found=?,
                       new_posts=?, duplicates=?, images_downloaded=?, captcha_events=1 WHERE id=?""",
                (t.replace(microsecond=0).isoformat(), totals["found"], totals["new"], totals["found"] - totals["new"],
                 totals["imgs"], run_id))
            conn.execute("UPDATE posts SET scraped_at=?, last_seen_at=? WHERE first_run_id=?",
                         (t.replace(microsecond=0).isoformat(), t.replace(microsecond=0).isoformat(), run_id))
        with session() as conn:
            analyse_project(conn, pid, preferred="offline")
        with session() as conn:
            from .generator import generate
            generate(conn, pid, 5, "idea", preferred="offline")
            generate(conn, pid, 1, "update", preferred="offline", make_images=True)
    with session() as conn:
        conn.execute("UPDATE ideas SET created_at=? WHERE 1=1", (now(),))
    return True


if __name__ == "__main__":
    import sys
    print("seeded" if seed_demo(force="--force" in sys.argv) else "database already has projects; use --force")
