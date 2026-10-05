"""Flask web application: Google Maps Competitor Update Intelligence Tool."""
import os
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from gmci import config, generator, repository as repo, trends
from gmci.ai import analysis, providers
from gmci.db import init_db, jload, row, rows, session
from gmci.jobs import live_available, manager
from gmci.seed import seed_demo

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config["TEMPLATES_AUTO_RELOAD"] = True


def bootstrap():
    init_db()
    if config.SEED_DEMO:
        seed_demo()
    if config.env_flag("GMCI_SCHEDULER", True):
        manager.start_scheduler()


@app.context_processor
def inject():
    with session() as conn:
        projects = rows(conn, "SELECT id, name FROM projects ORDER BY id")
    return {"all_projects": projects, "live_ok": live_available(), "media_url": repo.media_url}


@app.template_filter("dt")
def fmt_dt(value):
    if not value:
        return "-"
    return str(value).replace("T", " ")[:16]


@app.template_filter("shot")
def shot_url(path):
    if not path:
        return ""
    p = Path(path)
    if p.parent == config.SCREENSHOT_DIR:
        return url_for("screenshot", name=p.name)
    return repo.media_url(path)


def project_or_404(conn, pid):
    p = repo.get_project(conn, pid)
    if not p:
        abort(404)
    return p


# ------------------------------------------------------------------ projects

@app.route("/")
def home():
    with session() as conn:
        projects = repo.list_projects(conn)
        recent = rows(conn, """SELECT r.*, p.name AS project_name FROM scrape_runs r JOIN projects p ON p.id = r.project_id
                               ORDER BY r.id DESC LIMIT 5""")
    return render_template("home.html", projects=projects, recent=recent)


@app.post("/projects")
def create_project():
    f = request.form
    if not f.get("name", "").strip():
        flash("Give the project a name.", "error")
        return redirect(url_for("home"))
    with session() as conn:
        pid = repo.create_project(conn, f["name"].strip(), f.get("industry", ""), f.get("location", ""),
                                  f.get("own_name", "").strip(), f.get("own_url", "").strip(), f.get("own_address", ""))
        repo.set_keywords(conn, pid, f.get("keywords", "").replace("\n", ",").split(","))
    flash("Project created. Now add your competitors.", "ok")
    return redirect(url_for("competitors", pid=pid))


@app.route("/p/<int:pid>/settings", methods=["GET", "POST"])
def project_settings(pid):
    with session() as conn:
        p = project_or_404(conn, pid)
        if request.method == "POST":
            f = request.form
            repo.update_project(conn, pid, f["name"].strip() or p["name"], f.get("industry", ""), f.get("location", ""),
                                f.get("own_name", "").strip(), f.get("own_url", "").strip(), f.get("own_address", ""),
                                f.get("schedule_hours", 0))
            repo.set_keywords(conn, pid, f.get("keywords", "").replace("\n", ",").split(","))
            flash("Project saved.", "ok")
            return redirect(url_for("project_settings", pid=pid))
        kws = repo.keywords(conn, pid)
    return render_template("settings.html", p=p, keywords=kws)


@app.post("/p/<int:pid>/delete")
def delete_project(pid):
    with session() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
    flash("Project deleted. Competitor posts shared with other projects were kept.", "ok")
    return redirect(url_for("home"))


@app.route("/p/<int:pid>")
def dashboard(pid):
    with session() as conn:
        p = project_or_404(conn, pid)
        stats = repo.dashboard(conn, pid)
        tr = trends.topic_trends(conn, pid)["rows"][:6]
        kws = trends.keyword_trends(conn, pid, 12)
        comps = repo.competitors(conn, pid)
        latest, _ = repo.search_posts(conn, pid, limit=6, include_own=False)
        summary = analysis.latest_summary(conn, pid)
    return render_template("dashboard.html", p=p, s=stats, trends=tr, kws=kws, comps=comps, latest=latest,
                           summary=summary)


# ------------------------------------------------------------------ competitors

@app.route("/p/<int:pid>/competitors", methods=["GET", "POST"])
def competitors(pid):
    with session() as conn:
        p = project_or_404(conn, pid)
        if request.method == "POST":
            f = request.form
            name = f.get("name", "").strip()
            if not name:
                flash("Competitor name is required.", "error")
            else:
                bid, created = repo.add_competitor(conn, pid, name, f.get("maps_url", "").strip(), f.get("address", ""),
                                                   f.get("category", ""))
                flash(f"Added {name}." if created else
                      f"{name} already exists in the repository; linked the existing record to this project (no duplicate).", "ok")
            return redirect(url_for("competitors", pid=pid))
        comps = repo.competitors(conn, pid)
    return render_template("competitors.html", p=p, comps=comps)


@app.post("/p/<int:pid>/competitors/<int:bid>/edit")
def edit_competitor(pid, bid):
    f = request.form
    with session() as conn:
        repo.update_competitor(conn, bid, f["name"].strip(), f.get("maps_url", ""), f.get("address", ""), f.get("category", ""))
    flash("Competitor updated.", "ok")
    return redirect(url_for("competitors", pid=pid))


@app.post("/p/<int:pid>/competitors/<int:bid>/remove")
def remove_competitor(pid, bid):
    with session() as conn:
        repo.remove_competitor(conn, pid, bid)
    flash("Competitor removed from this project.", "ok")
    return redirect(url_for("competitors", pid=pid))


# ------------------------------------------------------------------ scraping

@app.post("/p/<int:pid>/scrape")
def start_scrape(pid):
    f = request.form
    with session() as conn:
        p = project_or_404(conn, pid)
        ids = [int(x) for x in f.getlist("business_ids") if x.isdigit()]
        if f.get("all"):
            ids = repo.project_business_ids(conn, pid)
        if f.get("include_own") and p["own_business_id"] and p["own_business_id"] not in ids:
            ids.append(p["own_business_id"])
    if not ids:
        flash("Select at least one competitor to scrape.", "error")
        return redirect(url_for("competitors", pid=pid))
    mode = f.get("mode", "demo")
    if mode == "live" and not live_available()[0]:
        flash(f"Live scraping is not available on this server ({live_available()[1]}). Using demo mode.", "error")
        mode = "demo"
    run_id = manager.start_scrape(pid, ids, mode, simulate_captcha=bool(f.get("simulate_captcha")))
    return redirect(url_for("run_detail", rid=run_id))


@app.route("/runs/<int:rid>")
def run_detail(rid):
    with session() as conn:
        run = row(conn, "SELECT * FROM scrape_runs WHERE id=?", (rid,))
        if not run:
            abort(404)
        p = project_or_404(conn, run["project_id"])
        items = rows(conn, "SELECT * FROM scrape_run_items WHERE run_id=? ORDER BY id", (rid,))
    job = manager.jobs.get(rid)
    return render_template("run.html", p=p, run=run, items=items, live_console=bool(job and job.mode == "live"),
                           log_lines=job.log_lines[-40:] if job else [])


@app.route("/api/runs/<int:rid>")
def run_api(rid):
    with session() as conn:
        run = row(conn, "SELECT * FROM scrape_runs WHERE id=?", (rid,))
        if not run:
            abort(404)
        items = rows(conn, "SELECT * FROM scrape_run_items WHERE run_id=? ORDER BY id", (rid,))
    for it in items:
        it["screenshot_url"] = shot_url(it["screenshot"])
    job = manager.jobs.get(rid)
    return jsonify(run=run, items=items, log=job.log_lines[-40:] if job else [], attached=bool(job))


@app.post("/runs/<int:rid>/action")
def run_action(rid):
    action = request.form.get("action")
    if action not in {"continue", "skip", "cancel"}:
        abort(400)
    if not manager.act(rid, action):
        flash("This run is no longer active (the server may have restarted).", "error")
    return redirect(url_for("run_detail", rid=rid))


@app.post("/runs/<int:rid>/console")
def run_console(rid):
    data = request.get_json(force=True, silent=True) or {}
    op = data.get("op", "screenshot")
    res = manager.console(rid, op, x=float(data.get("x", 0)), y=float(data.get("y", 0)), text=data.get("text", ""),
                          enter=bool(data.get("enter")))
    if res.get("screenshot"):
        res["screenshot_url"] = shot_url(res["screenshot"])
    return jsonify(res)


@app.route("/p/<int:pid>/runs")
def runs(pid):
    with session() as conn:
        p = project_or_404(conn, pid)
        history = rows(conn, "SELECT * FROM scrape_runs WHERE project_id=? ORDER BY id DESC", (pid,))
        items = rows(conn, """SELECT i.*, r.mode FROM scrape_run_items i JOIN scrape_runs r ON r.id=i.run_id
                              WHERE r.project_id=? ORDER BY i.id DESC LIMIT 300""", (pid,))
    return render_template("runs.html", p=p, history=history, items=items)


# ------------------------------------------------------------------ repository

@app.route("/p/<int:pid>/posts")
def posts(pid):
    a = request.args
    page = max(int(a["page"]) if a.get("page", "").isdigit() else 1, 1)
    with session() as conn:
        p = project_or_404(conn, pid)
        business_id = int(a["competitor"]) if a.get("competitor", "").isdigit() else None
        items, total = repo.search_posts(conn, pid, business_id, a.get("q", ""), a.get("topic", ""), a.get("keyword", ""),
                                         a.get("from", ""), a.get("to", ""), limit=30, offset=(page - 1) * 30)
        comps = repo.competitors(conn, pid)
        topics = repo.topics_for_project(conn, pid)
        kws = repo.keywords(conn, pid)
        top_kws = [k["keyword"] for k in trends.keyword_trends(conn, pid, 15)]
    return render_template("posts.html", p=p, items=items, total=total, comps=comps, topics=topics,
                           keywords=list(dict.fromkeys(kws + top_kws)), page=page, pages=(total + 29) // 30, args=a)


@app.route("/posts")
def all_posts():
    """Cross-project repository view."""
    a = request.args
    with session() as conn:
        pid = int(a["project"]) if a.get("project", "").isdigit() else None
        items, total = repo.search_posts(conn, pid, None, a.get("q", ""), a.get("topic", ""), a.get("keyword", ""),
                                         a.get("from", ""), a.get("to", ""), limit=60)
    return render_template("all_posts.html", items=items, total=total, args=a)


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    with session() as conn:
        post = repo.get_post(conn, post_id)
        if not post:
            abort(404)
        similar_ideas = rows(conn, "SELECT * FROM ideas WHERE similar_post_id=? ORDER BY id DESC LIMIT 5", (post_id,))
    return render_template("post.html", post=post, similar_ideas=similar_ideas)


@app.route("/media/<path:path>")
def media(path):
    return send_from_directory(config.MEDIA_DIR, path)


@app.route("/screenshots/<path:name>")
def screenshot(name):
    return send_from_directory(config.SCREENSHOT_DIR, name)


# ------------------------------------------------------------------ analysis & trends

@app.route("/p/<int:pid>/analysis", methods=["GET", "POST"])
def analysis_page(pid):
    with session() as conn:
        p = project_or_404(conn, pid)
        if request.method == "POST":
            preferred = request.form.get("provider", "")
            result = analysis.analyse_project(conn, pid, preferred, reanalyse=bool(request.form.get("reanalyse")))
            flash(f"Analysed {result['analysed']} posts using {result['provider']}.", "ok")
            return redirect(url_for("analysis_page", pid=pid))
        summary = analysis.latest_summary(conn, pid)
        history = rows(conn, "SELECT id, provider, posts_analyzed, created_at FROM analysis_runs WHERE project_id=? ORDER BY id DESC LIMIT 10", (pid,))
        unanalysed = row(conn, f"""SELECT COUNT(*) AS n FROM posts p LEFT JOIN post_analysis a ON a.post_id=p.id
            WHERE a.post_id IS NULL AND p.business_id IN ({",".join("?" * len(repo.project_business_ids(conn, pid, True))) or "NULL"})""",
                         repo.project_business_ids(conn, pid, True))["n"]
    return render_template("analysis.html", p=p, summary=summary, history=history, unanalysed=unanalysed,
                           providers=providers.statuses())


@app.route("/p/<int:pid>/trends")
def trends_page(pid):
    a = request.args
    with session() as conn:
        p = project_or_404(conn, pid)
        table = trends.topic_trends(conn, pid, a.get("from", ""), a.get("to", ""))
        history = trends.monthly_history(conn, pid)
        kws = trends.keyword_trends(conn, pid, 25)
        gaps = trends.gap_analysis(conn, pid)
        patterns = analysis.competitor_patterns(conn, pid)
    return render_template("trends.html", p=p, table=table, history=history, kws=kws, gaps=gaps, patterns=patterns, args=a)


# ------------------------------------------------------------------ generation

@app.route("/p/<int:pid>/ideas", methods=["GET", "POST"])
def ideas(pid):
    with session() as conn:
        p = project_or_404(conn, pid)
        if request.method == "POST":
            f = request.form
            kind = "update" if f.get("kind") == "update" else "idea"
            try:
                count = int(f.get("count", 5))
            except ValueError:
                count = 5
            res = generator.generate(conn, pid, count, kind, f.get("provider", ""), f.get("topic", ""),
                                     make_images=bool(f.get("make_images")))
            msg = (f"Generated {res['generated']} of {res['requested']} {kind}s with {', '.join(res['providers']) or '-'}; "
                   f"{res['rejected_as_duplicate']} candidates rejected as repeats of earlier ideas.")
            flash(msg, "ok" if res["generated"] == res["requested"] else "error")
            return redirect(url_for("ideas", pid=pid, batch=res["batch_id"], kind=kind))
        batch = request.args.get("batch", "")
        kind = request.args.get("kind", "")
        items = generator.list_ideas(conn, pid, kind, "")
        batches = rows(conn, """SELECT batch_id, kind, COUNT(*) AS n, MIN(created_at) AS created_at, MAX(provider) AS provider
                                FROM ideas WHERE project_id=? GROUP BY batch_id ORDER BY MIN(id) DESC""", (pid,))
        topics = [t["topic"] for t in trends.topic_trends(conn, pid)["rows"]]
    return render_template("ideas.html", p=p, items=items, batches=batches, batch=batch, kind=kind, topics=topics,
                           providers=providers.statuses())


@app.route("/idea/<int:idea_id>")
def idea_detail(idea_id):
    with session() as conn:
        idea = row(conn, "SELECT * FROM ideas WHERE id=?", (idea_id,))
        if not idea:
            abort(404)
        p = project_or_404(conn, idea["project_id"])
        idea["keywords_list"] = jload(idea["keywords"])
        inspired = [repo.get_post(conn, i) for i in jload(idea["inspired_by"])]
        similar = repo.get_post(conn, idea["similar_post_id"]) if idea["similar_post_id"] else None
    return render_template("idea.html", p=p, idea=idea, inspired=[i for i in inspired if i], similar=similar)


@app.post("/idea/<int:idea_id>/expand")
def expand_idea(idea_id):
    """Turn a saved idea into a complete Google Maps update on the same topic."""
    with session() as conn:
        idea = row(conn, "SELECT * FROM ideas WHERE id=?", (idea_id,))
        if not idea:
            abort(404)
        res = generator.generate(conn, idea["project_id"], 1, "update", request.form.get("provider", ""), idea["topic"] or "",
                                 make_images=True)
    if res["ids"]:
        return redirect(url_for("idea_detail", idea_id=res["ids"][0]))
    flash("Could not generate a new update that isn't a repeat; try another topic.", "error")
    return redirect(url_for("idea_detail", idea_id=idea_id))


# ------------------------------------------------------------------ discovery (bonus)

@app.route("/p/<int:pid>/discover", methods=["GET", "POST"])
def discover(pid):
    with session() as conn:
        p = project_or_404(conn, pid)
        if request.method == "POST":
            kws = request.form.getlist("keywords") or repo.keywords(conn, pid)
            mode = request.form.get("mode", "demo")
            if mode == "live" and not live_available()[0]:
                mode = "demo"
            manager.start_discovery(pid, kws, mode)
            flash(f"Searching Google Maps for: {', '.join(kws)}. Results appear below as they arrive.", "ok")
            return redirect(url_for("discover", pid=pid))
        found = rows(conn, "SELECT * FROM discovered_businesses WHERE project_id=? ORDER BY keyword, status, name", (pid,))
        kws = repo.keywords(conn, pid)
    return render_template("discover.html", p=p, found=found, keywords=kws)


@app.post("/p/<int:pid>/discover/<int:did>/<action>")
def discover_action(pid, did, action):
    with session() as conn:
        d = row(conn, "SELECT * FROM discovered_businesses WHERE id=? AND project_id=?", (did, pid))
        if not d:
            abort(404)
        if action == "add":
            bid, created = repo.add_competitor(conn, pid, d["name"], d["maps_url"], d["address"], d["category"])
            conn.execute("UPDATE discovered_businesses SET status='added', existing_business_id=? WHERE id=?", (bid, did))
            flash(f"Added {d['name']} to competitors" + ("" if created else " (matched an existing record, no duplicate created)"), "ok")
        elif action == "ignore":
            conn.execute("UPDATE discovered_businesses SET status='ignored' WHERE id=?", (did,))
    return redirect(url_for("discover", pid=pid))


# ------------------------------------------------------------------ settings

@app.route("/settings/ai", methods=["GET", "POST"])
def ai_settings():
    result = None
    if request.method == "POST":
        result = providers.test_provider(request.form.get("provider", ""))
        result["provider"] = request.form.get("provider")
    return render_template("ai.html", providers=providers.statuses(), result=result)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/health")
def health():
    with session() as conn:
        n = row(conn, "SELECT COUNT(*) AS n FROM posts")["n"]
    return jsonify(ok=True, posts=n, live_scraping=live_available()[0])


@app.errorhandler(404)
def not_found(_):
    return render_template("message.html", title="Not found", message="That page does not exist."), 404


bootstrap()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False, threaded=True)
