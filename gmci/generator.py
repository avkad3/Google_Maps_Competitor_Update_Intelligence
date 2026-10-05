"""Content idea and complete Google Maps update generator, with duplicate prevention.

Grounding: every request is built from the project's own repository (trending topics, recurring
keywords, offer mechanics, competitor example posts, topics the client is missing).

Duplicate prevention: each saved idea keeps a token ``signature``. New candidates are rejected
when they are too similar (Jaccard on title+topic tokens, or cosine on title+body) to any idea
already generated for the project, or to another candidate in the same batch. Previous titles are
also passed to the LLM as an exclusion list, and the loop asks for more until the requested count
is met (falling back to the offline generator for any shortfall).
"""
import json
import random
import uuid
from datetime import date

from . import images
from .ai import providers
from .ai.taxonomy import ANGLE_FIT, SUBJECTS
from .db import jdump, jload, now, row, rows
from .repository import keywords as project_keywords
from .repository import project_business_ids
from .textutil import cosine, jaccard, tokens
from .trends import gap_analysis, keyword_trends, topic_trends

MAX_UPDATE_CHARS = 1500  # Google Business Profile update limit
TITLE_SIM = 0.5
BODY_SIM = 0.62
COPY_SIM = 0.55          # flag generated copy that is too close to a competitor post


def _signature(topic, title):
    # Title tokens only: the topic is shared by many legitimately different ideas.
    return " ".join(sorted(set(tokens(title))))


class History:
    def __init__(self, conn, project_id):
        self.items = rows(conn, "SELECT id, topic, title, body, signature FROM ideas WHERE project_id=?", (project_id,))
        self.sigs = [set((i["signature"] or "").split()) for i in self.items]
        self.texts = [tokens(f"{i['title']} {i['body'] or ''}") for i in self.items]
        self.topics = [(i["topic"] or "").strip().lower() for i in self.items]
        self.rejected = 0

    def is_duplicate(self, topic, title, body=""):
        """Same headline (token overlap), or the same topic with substantially the same content."""
        sig = set(_signature(topic, title).split())
        text = tokens(f"{title} {body}")
        topic_key = (topic or "").strip().lower()
        for s, t, tp in zip(self.sigs, self.texts, self.topics):
            if jaccard(sig, s) >= TITLE_SIM:
                return True
            if tp == topic_key and cosine(text, t) >= BODY_SIM:
                return True
        return False

    def add(self, topic, title, body=""):
        self.sigs.append(set(_signature(topic, title).split()))
        self.texts.append(tokens(f"{title} {body}"))
        self.topics.append((topic or "").strip().lower())


def build_context(conn, project_id):
    project = row(conn, "SELECT * FROM projects WHERE id=?", (project_id,))
    own = row(conn, "SELECT * FROM businesses WHERE id=?", (project["own_business_id"],)) if project["own_business_id"] else None
    trends = topic_trends(conn, project_id)["rows"]
    gaps = gap_analysis(conn, project_id)
    kws = keyword_trends(conn, project_id, 20)
    ids = project_business_ids(conn, project_id)
    examples = []
    if ids:
        marks = ",".join("?" * len(ids))
        for t in trends[:8]:
            examples += rows(conn, f"""SELECT p.id, p.text, b.name AS business, a.main_topic, a.offer, a.cta FROM posts p
                JOIN businesses b ON b.id=p.business_id JOIN post_analysis a ON a.post_id=p.id
                WHERE p.business_id IN ({marks}) AND a.main_topic=? ORDER BY p.published_at DESC LIMIT 2""",
                             ids + [t["topic"]])
    offers = rows(conn, f"""SELECT a.offer FROM post_analysis a JOIN posts p ON p.id=a.post_id
                           WHERE a.offer != '' AND p.business_id IN ({",".join("?" * len(ids)) or "NULL"})
                           LIMIT 40""", ids)
    competitor_posts = rows(conn, f"""SELECT id, text FROM posts WHERE business_id IN ({",".join("?" * len(ids)) or "NULL"})""", ids)
    return {
        "project": project, "business": own["name"] if own else project["name"], "location": project["location"] or "",
        "industry": project["industry"] or "local business", "trends": trends, "gaps": gaps["missing"],
        "keywords": [k["keyword"] for k in kws], "project_keywords": project_keywords(conn, project_id),
        "examples": examples, "offers": list(dict.fromkeys(o["offer"] for o in offers))[:10],
        "competitor_posts": [(p["id"], tokens(p["text"])) for p in competitor_posts],
    }


def closest_competitor_post(ctx, text):
    best, best_id = 0.0, None
    toks = tokens(text)
    for pid, ptoks in ctx["competitor_posts"]:
        s = cosine(toks, ptoks)
        if s > best:
            best, best_id = s, pid
    return round(best, 3), best_id


# ------------------------------------------------------------------ LLM generation

def _llm_candidates(ctx, n, kind, history_titles, focus_topic, preferred):
    trends = [{"topic": t["topic"], "competitors_using": f"{t['competitors_using']}/{t['competitors_total']}",
               "share_of_posts": f"{t['post_pct']}%"} for t in ctx["trends"][:12]]
    examples = [{"post_id": e["id"], "competitor": e["business"], "topic": e["main_topic"], "text": e["text"][:400]}
                for e in ctx["examples"][:14]]
    want = ("complete Google Maps updates. Each needs: topic, title, angle (one line), body (the full update copy, "
            f"80-220 words, under {MAX_UPDATE_CHARS} characters, written in the business's own voice, no hashtags spam, "
            "mention the location naturally), keywords (3-6 local search phrases), cta (one of: Book, Order online, Buy, "
            "Learn more, Sign up, Call now), image_concept (what the photo should show), inspired_by (list of post_id "
            "values from the examples that informed it)") if kind == "update" else \
        ("content ideas. Each needs: topic, title (a specific, catchy headline), angle (2 sentences on what the update "
         "would say and why it works, citing the competitor trend it builds on), keywords (3-5), cta, image_concept, "
         "inspired_by (list of post_id values)")
    prompt = (
        f"Business: {ctx['business']} ({ctx['industry']}) in {ctx['location']}.\n"
        f"Project search keywords: {', '.join(ctx['project_keywords'])}\n"
        f"Competitor topic trends: {json.dumps(trends)}\n"
        f"Topics competitors use that this business has not covered: {', '.join(g['topic'] for g in ctx['gaps'][:8]) or 'none'}\n"
        f"Recurring competitor keywords: {', '.join(ctx['keywords'][:20])}\n"
        f"Offer mechanics competitors use: {', '.join(ctx['offers'])}\n"
        f"Example competitor posts: {json.dumps(examples, ensure_ascii=False)}\n"
        + (f"Focus every item on the topic: {focus_topic}.\n" if focus_topic else
           "Spread items across the trending and missing topics.\n")
        + f"Do NOT repeat or closely paraphrase any of these previously generated titles: {json.dumps(history_titles[-150:], ensure_ascii=False)}\n"
        f"Write {n} distinct {want}. Do not copy competitor wording. Return {{\"items\": [...]}}.")
    data, provider = providers.llm_json("You plan Google Business Profile (Google Maps) updates for local businesses. "
                                        "Answer with JSON only.", prompt, preferred, temperature=0.9)
    if not data:
        return [], provider
    items = data.get("items", []) if isinstance(data, dict) else data
    return [i for i in items if isinstance(i, dict) and i.get("title")], provider


# ------------------------------------------------------------------ offline generation

ANGLES = [
    ("tips", "{n} {topic_l} tips from our {area} experts", "Share {n} quick, practical tips about {topic_l} that customers can use at home, then invite them in for the professional version."),
    ("myth", "{topic} myths we hear every week in {area}", "Bust three common myths about {topic_l} in plain language; myth-busting posts get saved and shared."),
    ("offer", "{season} {topic_l} offer for {area}", "Run a time-bound {offer} on {topic_l}; competitors lean on offers, so make ours specific and easy to claim."),
    ("showcase", "Real results: a {topic_l} story from our chair", "Show one real customer result for {topic_l} with a short story of what was done and how long it took."),
    ("faq", "Your top {topic_l} questions, answered", "Answer the 3 questions customers ask most about {topic_l}, positioning the team as the local expert."),
    ("behind", "Behind the scenes: how we do {topic_l}", "Walk through the process, products and hygiene steps behind {topic_l} to build trust."),
    ("checklist", "Your {season} {topic_l} checklist", "A short seasonal checklist about {topic_l}, tied to {season} needs in {area}."),
    ("team", "Meet the {topic_l} specialist at {business}", "Introduce the team member who leads {topic_l}, their experience, and what to book them for."),
    ("compare", "{topic}: which option is right for you?", "Compare the options customers choose between for {topic_l}, with price ranges and who each suits."),
    ("launch", "New at {business}: {topic_l} {variant}", "Announce a new or refreshed {topic_l} service with what's included and an opening price."),
    ("testimonial", "What {area} customers say about our {topic_l}", "Feature a short customer quote about {topic_l} and the result they got."),
    ("first", "First time trying {topic_l}? Read this", "Reassure first-timers: what to expect, how long it takes and aftercare for {topic_l}."),
    ("mistakes", "{n} {topic_l} mistakes to avoid", "List the most common mistakes people make with {topic_l} and how our team fixes them."),
    ("cost", "How much does {topic_l} cost in {area}?", "Be transparent about price ranges for {topic_l}, what changes the price, and what is included at {business}."),
    ("aftercare", "{topic} aftercare: make your results last", "Give a simple aftercare routine for {topic_l} so results last longer, and suggest when to come back."),
    ("trend", "{topic} trends {area} is loving right now", "Showcase the {topic_l} styles and requests that are trending locally this {season}."),
    ("prep", "How to prepare for your {topic_l} appointment", "A short prep guide for {topic_l}: what to do the day before, what to bring and how long to plan for."),
    ("products", "The products we trust for {topic_l}", "Introduce the professional products and tools used for {topic_l} and why they were chosen."),
    ("local", "Why {area} chooses {business} for {topic_l}", "Make the local case: experience, reviews and convenience for {topic_l} near {area}."),
    ("duo", "Bring a friend: {topic_l} for two", "Pair booking idea for {topic_l}: book together and both get a small perk."),
    ("weekday", "Weekday {topic_l} slots are open", "Promote quieter weekday slots for {topic_l} with a small weekday-only perk."),
]
SEASONS = {1: "New Year", 2: "Valentine's", 3: "spring", 4: "summer", 5: "summer", 6: "monsoon", 7: "monsoon",
           8: "festive", 9: "festive", 10: "Diwali", 11: "wedding season", 12: "year-end"}
VARIANTS = ["package", "express session", "signature service", "add-on", "membership", "weekday special"]


def _offline_candidates(ctx, n, kind, focus_topic, seed):
    rnd = random.Random(seed)
    topics = [focus_topic] if focus_topic else \
        [g["topic"] for g in ctx["gaps"]] + [t["topic"] for t in ctx["trends"] if t["topic"] not in {g["topic"] for g in ctx["gaps"]}]
    topics = [t for t in topics if t and t != "Unclassified"] or ["Customer Experience"]
    area = (ctx["location"] or "your area").split(",")[0]
    season = SEASONS[date.today().month]
    kws = ctx["project_keywords"] + ctx["keywords"]
    combos = [(t, a, v) for t in topics for a in ANGLES for v in VARIANTS[:2]
              if a[0] in ANGLE_FIT.get(t, {a[0]})]
    rnd.shuffle(combos)
    # Spread across topics first (missing topics lead), then across angles
    combos.sort(key=lambda c: topics.index(c[0]) // 3 + rnd.random())
    out = []
    for topic, (angle, title_t, angle_t), variant in combos:
        price_offers = [o for o in ctx["offers"] if any(ch in o for ch in "%₹") or "flat" in o.lower()]
        offer = rnd.choice(price_offers) if price_offers else "an introductory price"
        subject = SUBJECTS.get(topic, topic.lower())
        fmt = dict(n=rnd.choice([3, 4, 5]), topic=subject.capitalize(), topic_l=subject, area=area, season=season,
                   business=ctx["business"], offer=offer, variant=variant)
        title = title_t.format(**fmt)
        title = title[0].upper() + title[1:]
        topic_kws = [k for k in kws if any(w in k for w in tokens(topic))][:2]
        local_kws = [k for k in ctx["project_keywords"] if area.lower() in k.lower()][:2] or ctx["project_keywords"][:1]
        item = {"topic": topic, "title": title, "angle": angle_t.format(**fmt),
                "keywords": list(dict.fromkeys(topic_kws + local_kws + [f"{topic.lower()} {area.lower()}"]))[:5],
                "cta": {"offer": "Book", "launch": "Book", "tips": "Learn more", "myth": "Learn more",
                        "faq": "Call now", "team": "Book"}.get(angle, "Book"),
                "image_concept": {"showcase": f"Side-by-side before/after photo of a {topic.lower()} result, natural light",
                                  "team": f"Portrait of the {topic.lower()} specialist at work, warm interior",
                                  "offer": f"Bright graphic with the offer price over a {topic.lower()} photo",
                                  "behind": f"Close-up of tools and products used for {topic.lower()}, clean workstation"
                                  }.get(angle, f"Real photo from {ctx['business']} illustrating {topic.lower()}, 4:3, no stock imagery"),
                "inspired_by": [e["id"] for e in ctx["examples"] if e["main_topic"] == topic][:2],
                "angle_key": angle}
        if kind == "update":
            item["body"] = _offline_body(item, fmt, ctx)
        out.append(item)
    return out  # the whole candidate space; the caller filters out repeats


def _offline_body(item, fmt, ctx):
    t, area, biz = fmt["topic_l"], fmt["area"], ctx["business"]
    openers = {
        "tips": f"Looking after your {t} between visits is easier than you think. Our team in {area} shares a few habits that make a real difference:",
        "myth": f"We hear a lot of myths about {t} at {biz}. Here is what is actually true:",
        "offer": f"This {fmt['season']}, treat yourself to {t} at {biz}, {area}. For a limited time we're offering {fmt['offer']}.",
        "showcase": f"Every result starts with a conversation. This week a client came to us in {area} wanting a change in {t}, and here is how it went.",
        "faq": f"Thinking about {t}? These are the questions we're asked most often at {biz}:",
        "behind": f"Ever wondered what goes into {t} at {biz}? Here's a look behind the scenes.",
        "checklist": f"{fmt['season'].capitalize()} is here, and so are new {t} needs. Your quick checklist:",
        "team": f"Say hello to the specialist who leads {t} at {biz}, {area}.",
        "compare": f"Not sure which {t} option suits you? Here's a simple guide from our team in {area}.",
        "launch": f"Something new at {biz}: our {t} {fmt['variant']} is now available in {area}.",
        "testimonial": f"Nothing makes us happier than notes like this one about our {t}.",
        "first": f"Trying {t} for the first time? Here's exactly what to expect at {biz}.",
        "mistakes": f"We see the same {t} mistakes again and again at {biz}. Avoid these and your results will last longer.",
        "cost": f"How much does {t} cost in {area}? Here's an honest breakdown from {biz}.",
        "aftercare": f"Great {t} results last longer with the right aftercare. Here's what our team recommends.",
        "trend": f"These are the {t} requests we're seeing most in {area} this {fmt['season']}.",
        "prep": f"Booked {t} at {biz}? Here's how to get the most out of your appointment.",
        "products": f"Quality matters. These are the professional products we trust for {t} at {biz}, and why.",
        "local": f"Families across {area} trust {biz} for {t}. Here's why they keep coming back.",
        "duo": f"Everything is better with a friend. Book {t} for two at {biz} and you both get a little extra.",
        "weekday": f"Skip the weekend rush: weekday {t} slots are open at {biz}, {area}.",
    }
    middle = {
        "tips": "1) Start with a consultation so we understand your needs.\n2) Follow the aftercare routine we recommend.\n3) Book regular maintenance before problems build up.",
        "myth": "Myth: it is only for special occasions. Fact: regular care gives better, longer-lasting results.\nMyth: it takes hours. Fact: most sessions fit into a lunch break.",
        "offer": "Slots fill quickly on weekends, so book a weekday visit to get the time you want.",
        "faq": "How long does it take? Usually under an hour.\nIs it suitable for everyone? We'll check during a free consultation.\nHow do I maintain it? We'll give you a simple aftercare plan.",
    }.get(item["angle_key"], "Our experienced team uses quality products, follows strict hygiene, and takes the time to get it right for you.")
    close = f"{item['cta']} today and mention this update when you visit {biz}, {area}."
    body = f"{openers.get(item['angle_key'], openers['tips'])}\n\n{middle}\n\n{close}"
    if area.lower() in biz.lower():  # "ABC Salon, Kharghar, Kharghar"
        body = body.replace(f"{biz}, {area}", biz)
    return body[:MAX_UPDATE_CHARS]


# ------------------------------------------------------------------ public API

def generate(conn, project_id, count: int, kind="idea", preferred="", focus_topic="", make_images=False):
    count = max(1, min(int(count), 100 if kind == "idea" else 20))
    ctx = build_context(conn, project_id)
    hist = History(conn, project_id)
    history_titles = [i["title"] for i in hist.items]
    accepted, providers_used, rounds = [], set(), 0
    batch_id = uuid.uuid4().hex[:10]
    while len(accepted) < count and rounds < 6:
        rounds += 1
        need = count - len(accepted)
        ask = min(need + max(2, need // 3), 12 if kind == "idea" else 5)
        cands, provider = ([], "offline") if preferred == "offline" else \
            _llm_candidates(ctx, ask, kind, history_titles + [a["title"] for a in accepted], focus_topic, preferred)
        if not cands:
            cands = _offline_candidates(ctx, need * 4 + 10, kind, focus_topic, seed=len(hist.items) * 7919 + rounds)
            provider = "offline"
        for c in cands:
            topic, title = str(c.get("topic") or focus_topic or "General"), str(c.get("title")).strip()
            body = str(c.get("body") or "")
            if hist.is_duplicate(topic, title, body):
                hist.rejected += 1
                continue
            hist.add(topic, title, body)
            c["provider"] = provider
            accepted.append(c)
            providers_used.add(provider)
            if len(accepted) >= count:
                break
        if provider == "offline" and len(accepted) < count and rounds >= 3:
            break
    saved = []
    for c in accepted:
        body = str(c.get("body") or c.get("angle") or "")[:MAX_UPDATE_CHARS] if kind == "update" else str(c.get("angle") or "")
        kws = c.get("keywords") or []
        if isinstance(kws, str):
            kws = [k.strip() for k in kws.split(",")]
        sim, sim_post = closest_competitor_post(ctx, f"{c['title']} {body}")
        image_path = ""
        if kind == "update" and make_images:
            image_path = _make_image(c, ctx, batch_id)
        cur = conn.execute(
            """INSERT INTO ideas (project_id, batch_id, kind, topic, title, body, keywords, cta, image_concept, image_path,
                   inspired_by, provider, signature, similarity, similar_post_id, angle, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, batch_id, kind, c.get("topic"), c["title"], body, jdump(kws[:8]), c.get("cta") or "Book",
             c.get("image_concept") or "", image_path, jdump(c.get("inspired_by") or []), c["provider"],
             _signature(c.get("topic") or "", c["title"]), sim, sim_post, c.get("angle") if kind == "update" else "",
             now()))
        saved.append(cur.lastrowid)
    return {"batch_id": batch_id, "requested": count, "generated": len(saved), "rejected_as_duplicate": hist.rejected,
            "providers": sorted(providers_used), "ids": saved}


def _make_image(item, ctx, batch_id):
    stem = f"{batch_id}-{uuid.uuid4().hex[:6]}"
    gem = providers.PROVIDERS["gemini"]
    if gem.configured():
        try:
            data = gem.generate_image(
                f"Photo for a Google Maps business update by {ctx['business']} ({ctx['industry']}, {ctx['location']}). "
                f"{item.get('image_concept')}. Realistic, 4:3, no text overlay.")
            if data:
                return images.save_bytes("generated", stem, data)
        except Exception as exc:
            gem.last_error = str(exc)[:300]
    return images.svg_card("generated", stem, item["title"], item.get("image_concept", ""), ctx["business"],
                           badge=item.get("topic", "")[:28])


def list_ideas(conn, project_id, kind="", batch_id="", limit=200):
    sql, params = "SELECT * FROM ideas WHERE project_id=?", [project_id]
    if kind:
        sql += " AND kind=?"
        params.append(kind)
    if batch_id:
        sql += " AND batch_id=?"
        params.append(batch_id)
    items = rows(conn, sql + " ORDER BY id DESC LIMIT ?", params + [limit])
    for i in items:
        i["keywords_list"] = jload(i["keywords"])
        i["inspired_list"] = jload(i["inspired_by"])
    return items
