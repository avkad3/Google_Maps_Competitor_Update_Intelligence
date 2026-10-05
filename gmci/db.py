"""SQLite persistence layer.

Design notes
- A *business* is a Google Maps profile and is stored once, globally. Projects link to businesses
  through ``project_competitors`` so the same competitor can sit in several projects without its
  posts being stored twice.
- A *post* belongs to a business and carries a unique ``fingerprint`` (see ``fingerprint.py``);
  the UNIQUE constraint is the last line of defence against duplicates on re-scrape.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    maps_url TEXT,
    url_key TEXT UNIQUE,            -- normalised identity (place id / cid / name+address)
    address TEXT,
    category TEXT,
    rating REAL,
    review_count INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT,
    location TEXT,
    own_business_id INTEGER REFERENCES businesses(id) ON DELETE SET NULL,
    schedule_hours INTEGER DEFAULT 0, -- 0 = no automatic re-scrape
    last_scheduled_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_competitors (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    notes TEXT,
    added_at TEXT NOT NULL,
    PRIMARY KEY (project_id, business_id)
);

CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    UNIQUE (project_id, keyword)
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL UNIQUE,
    fingerprint_basis TEXT,          -- which fields the fingerprint was built from
    post_url TEXT,
    text TEXT NOT NULL,
    published_at TEXT,               -- ISO date when it could be resolved
    published_raw TEXT,              -- what Maps showed, e.g. "3 weeks ago"
    cta_label TEXT,
    cta_url TEXT,
    source_ref TEXT,                 -- page URL / method the post was read from
    first_run_id INTEGER,
    scraped_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    times_seen INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_posts_business ON posts(business_id);
CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published_at);

CREATE TABLE IF NOT EXISTS post_media (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    source_url TEXT,
    local_path TEXT,
    UNIQUE (post_id, source_url)
);

CREATE TABLE IF NOT EXISTS post_analysis (
    post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    main_topic TEXT,
    sub_topic TEXT,
    keywords TEXT,                   -- JSON list
    content_type TEXT,
    cta TEXT,
    offer TEXT,
    provider TEXT,
    analyzed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,              -- live | demo
    trigger TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL,            -- queued | running | needs_verification | done | failed | cancelled
    message TEXT,
    started_at TEXT,
    ended_at TEXT,
    competitors_total INTEGER DEFAULT 0,
    competitors_done INTEGER DEFAULT 0,
    posts_found INTEGER DEFAULT 0,
    new_posts INTEGER DEFAULT 0,
    duplicates INTEGER DEFAULT 0,
    images_downloaded INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0,
    captcha_events INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scrape_run_items (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
    business_id INTEGER REFERENCES businesses(id) ON DELETE SET NULL,
    business_name TEXT,
    status TEXT NOT NULL,            -- pending | running | needs_verification | done | failed | skipped
    started_at TEXT,
    ended_at TEXT,
    posts_found INTEGER DEFAULT 0,
    new_posts INTEGER DEFAULT 0,
    duplicates INTEGER DEFAULT 0,
    images_downloaded INTEGER DEFAULT 0,
    captcha_required INTEGER DEFAULT 0,
    manual_intervention TEXT,
    error TEXT,
    screenshot TEXT
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    provider TEXT,
    posts_analyzed INTEGER,
    summary TEXT,                    -- JSON: repository level insights
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- idea | update
    topic TEXT,
    title TEXT NOT NULL,
    body TEXT,
    keywords TEXT,                   -- JSON list
    cta TEXT,
    image_concept TEXT,
    image_path TEXT,
    inspired_by TEXT,                -- JSON list of post ids
    provider TEXT,
    signature TEXT,                  -- normalised tokens used for similarity checks
    similarity REAL,                 -- highest similarity to any competitor post (0..1)
    similar_post_id INTEGER,
    angle TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ideas_project ON ideas(project_id);

CREATE TABLE IF NOT EXISTS discovered_businesses (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    keyword TEXT,
    name TEXT NOT NULL,
    maps_url TEXT,
    url_key TEXT,
    address TEXT,
    category TEXT,
    rating REAL,
    existing_business_id INTEGER,
    status TEXT NOT NULL DEFAULT 'new',  -- new | added | ignored | existing
    discovered_at TEXT NOT NULL,
    UNIQUE (project_id, url_key)
);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialised = False


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    global _initialised
    with _init_lock:
        if _initialised:
            return
        conn = connect()
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()
        _initialised = True


@contextmanager
def session():
    """One connection per call; commits on success, rolls back on error."""
    init_db()
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def jload(value, default=None):
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default if default is not None else []


def jdump(value) -> str:
    return json.dumps(value, ensure_ascii=False)
