"""Data access: projects, competitors, posts (with duplicate detection) and repository queries."""
from pathlib import Path

from . import config
from .db import jdump, jload, now, row, rows
from .fingerprint import business_key, clean_url, post_fingerprint
from .textutil import resolve_relative_date

# ---------------------------------------------------------------- businesses / projects


def upsert_business(conn, name, maps_url="", address="", category="", rating=None, review_count=None):
    """Find a business by its Maps identity, or create it. Returns ``(id, created)``."""
    key = business_key(name, maps_url, address)
    existing = row(conn, "SELECT id FROM businesses WHERE url_key = ?", (key,))
    ts = now()
    if existing:
        conn.execute(
            """UPDATE businesses SET name = COALESCE(NULLIF(?, ''), name),
                   maps_url = COALESCE(NULLIF(?, ''), maps_url), address = COALESCE(NULLIF(?, ''), address),
                   category = COALESCE(NULLIF(?, ''), category), rating = COALESCE(?, rating),
                   review_count = COALESCE(?, review_count), updated_at = ? WHERE id = ?""",
            (name, clean_url(maps_url), address, category, rating, review_count, ts, existing["id"]),
        )
        return existing["id"], False
    cur = conn.execute(
        """INSERT INTO businesses (name, maps_url, url_key, address, category, rating, review_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, clean_url(maps_url), key, address, category, rating, review_count, ts, ts),
    )
    return cur.lastrowid, True


def create_project(conn, name, industry="", location="", own_name="", own_url="", own_address=""):
    own_id = None
    if own_name or own_url:
        own_id, _ = upsert_business(conn, own_name or "Our profile", own_url, own_address)
    cur = conn.execute(
        "INSERT INTO projects (name, industry, location, own_business_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, industry, location, own_id, now()),
    )
    return cur.lastrowid


def update_project(conn, project_id, name, industry, location, own_name, own_url, own_address, schedule_hours):
    own_id = None
    if own_name or own_url:
        own_id, _ = upsert_business(conn, own_name or "Our profile", own_url, own_address)
    conn.execute(
        "UPDATE projects SET name=?, industry=?, location=?, own_business_id=?, schedule_hours=? WHERE id=?",
        (name, industry, location, own_id, int(schedule_hours or 0), project_id),
    )


def get_project(conn, project_id):
    p = row(conn, "SELECT * FROM projects WHERE id = ?", (project_id,))
    if p and p["own_business_id"]:
        p["own"] = row(conn, "SELECT * FROM businesses WHERE id = ?", (p["own_business_id"],))
    elif p:
        p["own"] = None
    return p


def list_projects(conn):
    return rows(conn, """
        SELECT p.*, b.name AS own_name,
               (SELECT COUNT(*) FROM project_competitors pc WHERE pc.project_id = p.id) AS competitor_count,
               (SELECT COUNT(*) FROM posts po JOIN project_competitors pc ON pc.business_id = po.business_id
                 WHERE pc.project_id = p.id) AS post_count
        FROM projects p LEFT JOIN businesses b ON b.id = p.own_business_id ORDER BY p.id""")


def add_competitor(conn, project_id, name, maps_url="", address="", category="", notes=""):
    business_id, created = upsert_business(conn, name, maps_url, address, category)
    conn.execute(
        "INSERT OR IGNORE INTO project_competitors (project_id, business_id, notes, added_at) VALUES (?, ?, ?, ?)",
        (project_id, business_id, notes, now()),
    )
    return business_id, created


def update_competitor(conn, business_id, name, maps_url, address, category):
    conn.execute(
        "UPDATE businesses SET name=?, maps_url=?, address=?, category=?, updated_at=? WHERE id=?",
        (name, clean_url(maps_url), address, category, now(), business_id),
    )


def remove_competitor(conn, project_id, business_id):
    """Unlink from the project. Posts stay in the repository if another project still uses the business."""
    conn.execute("DELETE FROM project_competitors WHERE project_id=? AND business_id=?", (project_id, business_id))
    still_used = row(conn, """SELECT 1 FROM project_competitors WHERE business_id=?
                              UNION SELECT 1 FROM projects WHERE own_business_id=?""", (business_id, business_id))
    if not still_used:
        conn.execute("DELETE FROM businesses WHERE id=?", (business_id,))


def competitors(conn, project_id):
    return rows(conn, """
        SELECT b.*, pc.notes, pc.added_at,
          (SELECT COUNT(*) FROM posts WHERE business_id = b.id) AS post_count,
          (SELECT MAX(published_at) FROM posts WHERE business_id = b.id) AS latest_post,
          (SELECT status FROM scrape_run_items i WHERE i.business_id = b.id ORDER BY i.id DESC LIMIT 1) AS last_status,
          (SELECT COALESCE(ended_at, started_at) FROM scrape_run_items i WHERE i.business_id = b.id ORDER BY i.id DESC LIMIT 1) AS last_scraped,
          (SELECT error FROM scrape_run_items i WHERE i.business_id = b.id ORDER BY i.id DESC LIMIT 1) AS last_error,
          (SELECT COUNT(*) FROM project_competitors x WHERE x.business_id = b.id) AS project_count
        FROM project_competitors pc JOIN businesses b ON b.id = pc.business_id
        WHERE pc.project_id = ? ORDER BY b.name""", (project_id,))


def keywords(conn, project_id):
    return [r["keyword"] for r in rows(conn, "SELECT keyword FROM keywords WHERE project_id=? ORDER BY id", (project_id,))]


def set_keywords(conn, project_id, words):
    conn.execute("DELETE FROM keywords WHERE project_id=?", (project_id,))
    for w in words:
        w = w.strip()
        if w:
            conn.execute("INSERT OR IGNORE INTO keywords (project_id, keyword) VALUES (?, ?)", (project_id, w))


# ---------------------------------------------------------------- posts

def store_post(conn, business_id, post: dict, run_id=None):
    """Insert a scraped post unless it is already in the repository.

    Returns ``(post_id, is_new)``. Duplicates only bump ``last_seen_at``/``times_seen``.
    """
    biz = row(conn, "SELECT url_key FROM businesses WHERE id=?", (business_id,))
    published_raw = post.get("published_raw") or ""
    published_at = post.get("published_at") or resolve_relative_date(published_raw)
    fp, basis = post_fingerprint(biz["url_key"], post["text"], post.get("post_url", ""), published_at or "")
    existing = row(conn, "SELECT id FROM posts WHERE fingerprint=?", (fp,))
    ts = now()
    if existing:
        conn.execute("UPDATE posts SET last_seen_at=?, times_seen=times_seen+1 WHERE id=?", (ts, existing["id"]))
        return existing["id"], False
    cur = conn.execute(
        """INSERT INTO posts (business_id, fingerprint, fingerprint_basis, post_url, text, published_at, published_raw,
               cta_label, cta_url, source_ref, first_run_id, scraped_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (business_id, fp, basis, post.get("post_url") or "", post["text"].strip(), published_at, published_raw,
         post.get("cta_label") or "", post.get("cta_url") or "", post.get("source_ref") or "", run_id,
         post.get("scraped_at") or ts, ts),
    )
    return cur.lastrowid, True


def add_media(conn, post_id, source_url, local_path):
    conn.execute("INSERT OR IGNORE INTO post_media (post_id, source_url, local_path) VALUES (?, ?, ?)",
                 (post_id, source_url, local_path))


def media_url(local_path: str) -> str:
    if not local_path:
        return ""
    try:
        return "/media/" + Path(local_path).resolve().relative_to(config.MEDIA_DIR).as_posix()
    except ValueError:
        return "/media/" + Path(local_path).name


def search_posts(conn, project_id=None, business_id=None, q="", topic="", keyword="", date_from="", date_to="",
                 limit=60, offset=0, include_own=True):
    where, params = ["1=1"], []
    if project_id:
        biz_filter = "SELECT business_id FROM project_competitors WHERE project_id = ?"
        params.append(project_id)
        if include_own:
            biz_filter += " UNION SELECT own_business_id FROM projects WHERE id = ? AND own_business_id IS NOT NULL"
            params.append(project_id)
        where.append(f"p.business_id IN ({biz_filter})")
    if business_id:
        where.append("p.business_id = ?")
        params.append(business_id)
    if q:
        where.append("(p.text LIKE ? OR b.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if topic:
        where.append("a.main_topic = ?")
        params.append(topic)
    if keyword:
        where.append("(a.keywords LIKE ? OR p.text LIKE ?)")
        params += [f"%{keyword.lower()}%", f"%{keyword}%"]
    if date_from:
        where.append("p.published_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("p.published_at <= ?")
        params.append(date_to)
    sql_where = " AND ".join(where)
    total = conn.execute(f"""SELECT COUNT(*) FROM posts p JOIN businesses b ON b.id = p.business_id
                             LEFT JOIN post_analysis a ON a.post_id = p.id WHERE {sql_where}""", params).fetchone()[0]
    items = rows(conn, f"""
        SELECT p.*, b.name AS business_name, b.maps_url, a.main_topic, a.sub_topic, a.keywords AS kw_json,
               a.content_type, a.cta AS cta_detected, a.offer, a.provider AS analysis_provider
        FROM posts p JOIN businesses b ON b.id = p.business_id
        LEFT JOIN post_analysis a ON a.post_id = p.id
        WHERE {sql_where}
        ORDER BY COALESCE(p.published_at, substr(p.scraped_at, 1, 10)) DESC, p.id DESC LIMIT ? OFFSET ?""",
                 params + [limit, offset])
    attach_media(conn, items)
    return items, total


def attach_media(conn, items):
    for it in items:
        it["keywords_list"] = jload(it.get("kw_json"))
        media = rows(conn, "SELECT * FROM post_media WHERE post_id=? ORDER BY id", (it["id"],))
        for m in media:
            m["url"] = media_url(m["local_path"]) if m["local_path"] else m["source_url"]
        it["media"] = media
        it["projects"] = [r["name"] for r in rows(conn, """SELECT pr.name FROM projects pr
            JOIN project_competitors pc ON pc.project_id = pr.id WHERE pc.business_id = ?
            UNION SELECT pr.name FROM projects pr WHERE pr.own_business_id = ?""", (it["business_id"], it["business_id"]))]
    return items


def get_post(conn, post_id):
    items = rows(conn, """SELECT p.*, b.name AS business_name, b.maps_url, a.main_topic, a.sub_topic,
                          a.keywords AS kw_json, a.content_type, a.cta AS cta_detected, a.offer,
                          a.provider AS analysis_provider, a.analyzed_at
                          FROM posts p JOIN businesses b ON b.id = p.business_id
                          LEFT JOIN post_analysis a ON a.post_id = p.id WHERE p.id = ?""", (post_id,))
    attach_media(conn, items)
    if items:
        items[0]["first_run"] = row(conn, "SELECT * FROM scrape_runs WHERE id=?", (items[0]["first_run_id"],)) \
            if items[0]["first_run_id"] else None
    return items[0] if items else None


def project_business_ids(conn, project_id, include_own=False):
    ids = [r["business_id"] for r in rows(conn, "SELECT business_id FROM project_competitors WHERE project_id=?", (project_id,))]
    if include_own:
        p = row(conn, "SELECT own_business_id FROM projects WHERE id=?", (project_id,))
        if p and p["own_business_id"]:
            ids.append(p["own_business_id"])
    return ids


def save_analysis(conn, post_id, result: dict, provider: str):
    conn.execute(
        """INSERT INTO post_analysis (post_id, main_topic, sub_topic, keywords, content_type, cta, offer, provider, analyzed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(post_id) DO UPDATE SET main_topic=excluded.main_topic, sub_topic=excluded.sub_topic,
             keywords=excluded.keywords, content_type=excluded.content_type, cta=excluded.cta, offer=excluded.offer,
             provider=excluded.provider, analyzed_at=excluded.analyzed_at""",
        (post_id, result.get("main_topic"), result.get("sub_topic"), jdump(result.get("keywords") or []),
         result.get("content_type"), result.get("cta"), result.get("offer"), provider, now()),
    )


def topics_for_project(conn, project_id):
    ids = project_business_ids(conn, project_id, include_own=True)
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    return [r["main_topic"] for r in rows(conn, f"""SELECT DISTINCT a.main_topic FROM post_analysis a
        JOIN posts p ON p.id = a.post_id WHERE p.business_id IN ({marks}) AND a.main_topic IS NOT NULL
        ORDER BY a.main_topic""", ids)]


# ---------------------------------------------------------------- dashboard

def dashboard(conn, project_id):
    ids = project_business_ids(conn, project_id)
    marks = ",".join("?" * len(ids)) or "NULL"
    total_posts = conn.execute(f"SELECT COUNT(*) FROM posts WHERE business_id IN ({marks})", ids).fetchone()[0]
    analysed = conn.execute(f"""SELECT COUNT(*) FROM post_analysis a JOIN posts p ON p.id=a.post_id
                                WHERE p.business_id IN ({marks})""", ids).fetchone()[0]
    last_run = row(conn, "SELECT * FROM scrape_runs WHERE project_id=? ORDER BY id DESC LIMIT 1", (project_id,))
    failed = conn.execute("""SELECT COUNT(*) FROM scrape_run_items i JOIN scrape_runs r ON r.id=i.run_id
                             WHERE r.project_id=? AND i.status='failed'""", (project_id,)).fetchone()[0]
    captcha = conn.execute("""SELECT COUNT(*) FROM scrape_run_items i JOIN scrape_runs r ON r.id=i.run_id
                              WHERE r.project_id=? AND i.captcha_required=1""", (project_id,)).fetchone()[0]
    ideas = conn.execute("SELECT COUNT(*) FROM ideas WHERE project_id=?", (project_id,)).fetchone()[0]
    updates = conn.execute("SELECT COUNT(*) FROM ideas WHERE project_id=? AND kind='update'", (project_id,)).fetchone()[0]
    return {
        "competitors": len(ids),
        "total_posts": total_posts,
        "analysed": analysed,
        "new_last": last_run["new_posts"] if last_run else 0,
        "dupes_last": last_run["duplicates"] if last_run else 0,
        "failed": failed,
        "captcha": captcha,
        "last_run": last_run,
        "generated": ideas,
        "generated_updates": updates,
        "runs": conn.execute("SELECT COUNT(*) FROM scrape_runs WHERE project_id=?", (project_id,)).fetchone()[0],
    }
