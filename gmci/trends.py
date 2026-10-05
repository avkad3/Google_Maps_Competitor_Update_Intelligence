"""Trend analysis across the competitor repository, plus own-profile gap analysis."""
from collections import Counter, defaultdict

from .db import jload, row, rows
from .repository import project_business_ids


def _analysed_posts(conn, business_ids, date_from="", date_to=""):
    if not business_ids:
        return []
    marks = ",".join("?" * len(business_ids))
    sql = f"""SELECT p.id, p.business_id, p.published_at, b.name AS business_name, a.main_topic, a.sub_topic,
                     a.keywords, a.content_type, a.offer
              FROM posts p JOIN businesses b ON b.id = p.business_id JOIN post_analysis a ON a.post_id = p.id
              WHERE p.business_id IN ({marks})"""
    params = list(business_ids)
    if date_from:
        sql += " AND p.published_at >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND p.published_at <= ?"
        params.append(date_to)
    return rows(conn, sql, params)


def topic_trends(conn, project_id, date_from="", date_to=""):
    """Rows like the assignment's example: topic, competitors using it (of N), occurrence %."""
    comp_ids = project_business_ids(conn, project_id)
    posts = _analysed_posts(conn, comp_ids, date_from, date_to)
    total_comp = len(comp_ids)
    total_posts = len(posts)
    by_topic = defaultdict(lambda: {"posts": 0, "competitors": set(), "subs": Counter(), "latest": ""})
    for p in posts:
        t = by_topic[p["main_topic"] or "Unclassified"]
        t["posts"] += 1
        t["competitors"].add(p["business_id"])
        if p["sub_topic"]:
            t["subs"][p["sub_topic"]] += 1
        t["latest"] = max(t["latest"], p["published_at"] or "")
    table = []
    for name, t in by_topic.items():
        table.append({
            "topic": name, "competitors_using": len(t["competitors"]), "competitors_total": total_comp,
            "competitor_pct": round(100 * len(t["competitors"]) / total_comp) if total_comp else 0,
            "posts": t["posts"], "post_pct": round(100 * t["posts"] / total_posts, 1) if total_posts else 0,
            "top_sub": t["subs"].most_common(1)[0][0] if t["subs"] else "", "latest": t["latest"],
        })
    table.sort(key=lambda r: (-r["competitors_using"], -r["posts"]))
    return {"rows": table, "total_competitors": total_comp, "total_posts": total_posts}


def monthly_history(conn, project_id, top_n=6):
    """Historical trend tracking: posts per topic per month for the top topics."""
    posts = _analysed_posts(conn, project_business_ids(conn, project_id))
    top = [t for t, _ in Counter(p["main_topic"] for p in posts).most_common(top_n)]
    months = sorted({(p["published_at"] or "")[:7] for p in posts if p["published_at"]})[-12:]
    grid = {t: {m: 0 for m in months} for t in top}
    for p in posts:
        m = (p["published_at"] or "")[:7]
        if p["main_topic"] in grid and m in grid[p["main_topic"]]:
            grid[p["main_topic"]][m] += 1
    return {"months": months, "series": [{"topic": t, "counts": [grid[t][m] for m in months]} for t in top]}


def keyword_trends(conn, project_id, limit=30):
    posts = _analysed_posts(conn, project_business_ids(conn, project_id))
    kw_posts, kw_comp = Counter(), defaultdict(set)
    for p in posts:
        for k in set(jload(p["keywords"])):
            kw_posts[k] += 1
            kw_comp[k].add(p["business_id"])
    return [{"keyword": k, "posts": n, "competitors": len(kw_comp[k])} for k, n in kw_posts.most_common(limit)]


def gap_analysis(conn, project_id):
    """What competitors publish that the client's own profile does not (bonus feature)."""
    project = row(conn, "SELECT * FROM projects WHERE id=?", (project_id,))
    trends = topic_trends(conn, project_id)["rows"]
    own_id = project and project["own_business_id"]
    own_posts = _analysed_posts(conn, [own_id]) if own_id else []
    own_topics = Counter(p["main_topic"] for p in own_posts)
    own_types = Counter(p["content_type"] for p in own_posts)
    comp_posts = _analysed_posts(conn, project_business_ids(conn, project_id))
    comp_types = Counter(p["content_type"] for p in comp_posts)
    missing = [t for t in trends if t["topic"] not in own_topics and t["competitors_using"] >= 2]
    covered = [dict(t, own_posts=own_topics[t["topic"]]) for t in trends if t["topic"] in own_topics]
    n_comp = max(len(project_business_ids(conn, project_id)), 1)
    recs = []
    for t in missing[:5]:
        recs.append(f"Start covering '{t['topic']}': {t['competitors_using']} of {t['competitors_total']} competitors "
                    f"post about it ({t['posts']} posts) and your profile has none.")
    avg_comp = len(comp_posts) / n_comp
    if own_id and len(own_posts) < avg_comp:
        recs.append(f"Post more often: competitors average {avg_comp:.1f} updates each, your profile has {len(own_posts)}.")
    for ctype, n in comp_types.most_common(3):
        if own_types[ctype] == 0 and ctype != "Update":
            recs.append(f"Try the '{ctype}' format, used in {n} competitor posts but never on your profile.")
    if not own_id:
        recs.insert(0, "Add your own Google Maps profile to the project to compare it with competitors.")
    elif not own_posts:
        recs.insert(0, "Scrape your own profile so its updates can be compared with competitors.")
    return {"own_posts": len(own_posts), "missing": missing, "covered": covered, "recommendations": recs,
            "has_own": bool(own_id)}
