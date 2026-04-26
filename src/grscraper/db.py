import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from . import config
from .models import Business, Review

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  input_value       TEXT NOT NULL,
  input_type        TEXT NOT NULL,
  place_fingerprint TEXT,
  google_kg_id      TEXT,
  canonical_url     TEXT,
  name              TEXT,
  address           TEXT,
  category          TEXT,
  phone             TEXT,
  website           TEXT,
  hours_json        TEXT,
  plus_code         TEXT,
  latitude          REAL,
  longitude         REAL,
  overall_rating    REAL,
  review_count      INTEGER,
  status            TEXT NOT NULL DEFAULT 'queued',
  status_reason     TEXT,
  retry_count       INTEGER NOT NULL DEFAULT 0,
  created_at        TEXT NOT NULL,
  updated_at        TEXT NOT NULL,
  UNIQUE (place_fingerprint)
);

CREATE TABLE IF NOT EXISTS reviews (
  review_id         TEXT PRIMARY KEY,
  business_id       INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  reviewer_name     TEXT,
  reviewer_url      TEXT,
  reviewer_photo    TEXT,
  reviewer_reviews  INTEGER,
  reviewer_photos   INTEGER,
  rating            INTEGER,
  relative_date     TEXT,
  review_text       TEXT,
  review_lang       TEXT,
  photo_urls_json   TEXT,
  owner_reply       TEXT,
  owner_reply_date  TEXT,
  scraped_at        TEXT NOT NULL,
  scraper_version   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_business ON reviews(business_id);
CREATE INDEX IF NOT EXISTS idx_businesses_status ON businesses(status);

CREATE TABLE IF NOT EXISTS scrape_runs (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at         TEXT NOT NULL,
  finished_at        TEXT,
  workers            INTEGER NOT NULL,
  businesses_total   INTEGER,
  businesses_done    INTEGER,
  businesses_failed  INTEGER,
  reviews_added      INTEGER,
  notes              TEXT
);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or config.DB_PATH
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    return path


@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def insert_business(conn: sqlite3.Connection, b: Business) -> int | None:
    """Insert if not present. Returns row id, or None if it was a duplicate."""
    now = utcnow()
    if b.place_fingerprint:
        existing = conn.execute(
            "SELECT id FROM businesses WHERE place_fingerprint = ?",
            (b.place_fingerprint,),
        ).fetchone()
        if existing:
            return None
    existing = conn.execute(
        "SELECT id FROM businesses WHERE input_value = ? AND input_type = ?",
        (b.input_value, b.input_type),
    ).fetchone()
    if existing:
        return None
    cur = conn.execute(
        """
        INSERT INTO businesses
          (input_value, input_type, place_fingerprint, google_kg_id, canonical_url,
           name, address, category, phone, website, hours_json, plus_code,
           latitude, longitude, overall_rating, review_count,
           status, status_reason, retry_count, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            b.input_value, b.input_type, b.place_fingerprint, b.google_kg_id, b.canonical_url,
            b.name, b.address, b.category, b.phone, b.website, b.hours_json, b.plus_code,
            b.latitude, b.longitude, b.overall_rating, b.review_count,
            b.status, b.status_reason, b.retry_count, now, now,
        ),
    )
    return cur.lastrowid


def update_business(conn: sqlite3.Connection, b: Business) -> None:
    if b.id is None:
        raise ValueError("Business.id required to update")
    conn.execute(
        """
        UPDATE businesses SET
          place_fingerprint = ?, google_kg_id = ?, canonical_url = ?,
          name = ?, address = ?, category = ?, phone = ?, website = ?,
          hours_json = ?, plus_code = ?, latitude = ?, longitude = ?,
          overall_rating = ?, review_count = ?,
          status = ?, status_reason = ?, retry_count = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            b.place_fingerprint, b.google_kg_id, b.canonical_url,
            b.name, b.address, b.category, b.phone, b.website,
            b.hours_json, b.plus_code, b.latitude, b.longitude,
            b.overall_rating, b.review_count,
            b.status, b.status_reason, b.retry_count, utcnow(),
            b.id,
        ),
    )


def row_to_business(row: sqlite3.Row) -> Business:
    return Business(
        id=row["id"],
        input_value=row["input_value"],
        input_type=row["input_type"],
        place_fingerprint=row["place_fingerprint"],
        google_kg_id=row["google_kg_id"],
        canonical_url=row["canonical_url"],
        name=row["name"],
        address=row["address"],
        category=row["category"],
        phone=row["phone"],
        website=row["website"],
        hours_json=row["hours_json"],
        plus_code=row["plus_code"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        overall_rating=row["overall_rating"],
        review_count=row["review_count"],
        status=row["status"],
        status_reason=row["status_reason"],
        retry_count=row["retry_count"],
    )


def fetch_next_businesses(
    conn: sqlite3.Connection,
    limit: int,
    statuses: tuple[str, ...] = ("queued", "resolved", "failed"),
    max_retries: int = config.MAX_RETRIES,
) -> list[Business]:
    placeholders = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"""
        SELECT * FROM businesses
        WHERE status IN ({placeholders}) AND retry_count < ?
        ORDER BY id
        LIMIT ?
        """,
        (*statuses, max_retries, limit),
    ).fetchall()
    return [row_to_business(r) for r in rows]


def upsert_review(conn: sqlite3.Connection, r: Review) -> bool:
    """Insert if absent. Returns True if inserted, False if duplicate."""
    photos_json = json.dumps(r.photo_urls) if r.photo_urls else None
    try:
        conn.execute(
            """
            INSERT INTO reviews
              (review_id, business_id, reviewer_name, reviewer_url, reviewer_photo,
               reviewer_reviews, reviewer_photos, rating, relative_date, review_text,
               review_lang, photo_urls_json, owner_reply, owner_reply_date,
               scraped_at, scraper_version)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                r.review_id, r.business_id, r.reviewer_name, r.reviewer_url, r.reviewer_photo,
                r.reviewer_reviews, r.reviewer_photos, r.rating, r.relative_date, r.review_text,
                r.review_lang, photos_json, r.owner_reply, r.owner_reply_date,
                r.scraped_at or utcnow(), r.scraper_version or config.SCRAPER_VERSION,
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM businesses GROUP BY status"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def reset_status(conn: sqlite3.Connection, from_status: str, to_status: str = "queued") -> int:
    cur = conn.execute(
        "UPDATE businesses SET status = ?, retry_count = 0, status_reason = NULL, updated_at = ? WHERE status = ?",
        (to_status, utcnow(), from_status),
    )
    return cur.rowcount


def start_run(conn: sqlite3.Connection, workers: int, total: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO scrape_runs (started_at, workers, businesses_total, businesses_done, businesses_failed, reviews_added)
        VALUES (?, ?, ?, 0, 0, 0)
        """,
        (utcnow(), workers, total),
    )
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    done: int,
    failed: int,
    reviews_added: int,
    notes: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE scrape_runs SET finished_at = ?, businesses_done = ?, businesses_failed = ?, reviews_added = ?, notes = ?
        WHERE id = ?
        """,
        (utcnow(), done, failed, reviews_added, notes, run_id),
    )
