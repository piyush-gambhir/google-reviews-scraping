"""Build the canonical result document from the database.

`export.py` writes files for humans. This builds the same data in memory as a
single versioned envelope, which is what deployed runs hand to a sink.

The per-business objects here are byte-for-byte what `export combined` emits
per line, so any consumer written against that format keeps working — it just
reads `payload["businesses"]` instead of the bare list.

Shape is pinned by schemas/scrape-result.v1.json.
"""

import json
import sqlite3
from datetime import UTC, datetime

from . import config
from .db import connect

# Columns that exist only to drive the scraper's own queue and carry no
# meaning for a consumer.
_INTERNAL_BUSINESS_COLUMNS = ("status", "status_reason", "retry_count")


def _decode_photo_urls(review: dict) -> None:
    raw = review.pop("photo_urls_json", None)
    if not raw:
        review["photo_urls"] = []
        return
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        decoded = []
    review["photo_urls"] = decoded if isinstance(decoded, list) else []


def business_rows(conn: sqlite3.Connection, *, only_done: bool = False) -> list[dict]:
    """Return every business with its reviews nested under `reviews`."""
    sql = "SELECT * FROM businesses"
    params: tuple = ()
    if only_done:
        sql += " WHERE status = ?"
        params = ("done",)
    sql += " ORDER BY id"

    out: list[dict] = []
    for brow in conn.execute(sql, params).fetchall():
        biz = dict(brow)
        reviews = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM reviews WHERE business_id = ? ORDER BY review_id",
                (biz["id"],),
            ).fetchall()
        ]
        for review in reviews:
            _decode_photo_urls(review)
        biz["reviews"] = reviews
        out.append(biz)
    return out


def build(
    run_result: dict | None = None,
    *,
    only_done: bool = False,
    include_internal: bool = True,
) -> dict:
    """Assemble the full result envelope.

    `run_result` is the dict returned by runner.run(); omit it for a snapshot
    of whatever is already stored. `include_internal=False` drops the queue
    bookkeeping columns, which is what you want when publishing to a consumer
    that has no idea what `retry_count` means.
    """
    with connect() as conn:
        businesses = business_rows(conn, only_done=only_done)

    if not include_internal:
        for biz in businesses:
            for column in _INTERNAL_BUSINESS_COLUMNS:
                biz.pop(column, None)

    run = dict(run_result or {})
    return {
        "schema_version": config.SCHEMA_VERSION,
        "scraper_version": config.SCRAPER_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run": {
            "total": run.get("total", 0),
            "done": run.get("done", 0),
            "failed": run.get("failed", 0),
            "blocked": bool(run.get("blocked", False)),
            "reviews_added": run.get("reviews_added", 0),
        },
        "businesses": businesses,
    }
