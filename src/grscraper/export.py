import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from . import config
from .db import connect

REVIEW_COLUMNS = [
    "review_id", "business_id", "business_name", "business_address",
    "place_fingerprint", "google_kg_id", "canonical_url",
    "reviewer_name", "reviewer_url", "reviewer_photo",
    "reviewer_reviews", "reviewer_photos",
    "rating", "relative_date", "review_text", "review_lang",
    "photo_urls_json", "owner_reply", "owner_reply_date",
    "scraped_at", "scraper_version",
]

BUSINESS_COLUMNS = [
    "id", "input_value", "input_type", "place_fingerprint", "google_kg_id",
    "canonical_url", "name", "address", "category", "phone", "website",
    "hours_json", "plus_code", "latitude", "longitude",
    "overall_rating", "review_count",
    "status", "status_reason", "retry_count", "created_at", "updated_at",
]


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _ensure_export_dir() -> Path:
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return config.EXPORT_DIR


def export_reviews(fmt: str = "csv") -> Path:
    out_dir = _ensure_export_dir()
    out = out_dir / f"reviews_{_ts()}.{fmt}"
    sql = """
        SELECT r.*, b.name AS business_name, b.address AS business_address,
               b.place_fingerprint, b.google_kg_id, b.canonical_url
        FROM reviews r JOIN businesses b ON r.business_id = b.id
        ORDER BY b.id, r.review_id
    """
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
    _write_rows(out, rows, REVIEW_COLUMNS, fmt)
    return out


def export_businesses(fmt: str = "json") -> Path:
    out_dir = _ensure_export_dir()
    out = out_dir / f"businesses_{_ts()}.{fmt}"
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM businesses ORDER BY id").fetchall()]
    _write_rows(out, rows, BUSINESS_COLUMNS, fmt)
    return out


def export_combined(fmt: str = "ndjson") -> Path:
    if fmt != "ndjson":
        raise ValueError("combined export supports only ndjson")
    out_dir = _ensure_export_dir()
    out = out_dir / f"combined_{_ts()}.ndjson"
    with connect() as conn, out.open("w", encoding="utf-8") as fh:
        for brow in conn.execute("SELECT * FROM businesses ORDER BY id").fetchall():
            biz = dict(brow)
            reviews = [dict(r) for r in conn.execute(
                "SELECT * FROM reviews WHERE business_id = ? ORDER BY review_id",
                (biz["id"],),
            ).fetchall()]
            for r in reviews:
                if r.get("photo_urls_json"):
                    try:
                        r["photo_urls"] = json.loads(r["photo_urls_json"])
                    except json.JSONDecodeError:
                        r["photo_urls"] = []
                else:
                    r["photo_urls"] = []
                r.pop("photo_urls_json", None)
            biz["reviews"] = reviews
            fh.write(json.dumps(biz, ensure_ascii=False) + "\n")
    return out


def _write_rows(path: Path, rows: list[dict], columns: list[str], fmt: str) -> None:
    if fmt == "csv":
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c) for c in columns})
    elif fmt == "json":
        with path.open("w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
    elif fmt == "ndjson":
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    else:
        raise ValueError(f"unknown format: {fmt}")
