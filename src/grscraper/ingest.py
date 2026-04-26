import csv
from pathlib import Path

from .db import connect, insert_business, transaction
from .models import Business
from .url import classify_input, parse_maps_url


def _iter_rows(path: Path):
    """Yield (value, type|None) tuples from a CSV or newline file.

    CSV with header `value` or `value,type` is honored. Otherwise treat
    every non-empty line as a value.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    head = lines[0].strip().lower() if lines else ""
    has_csv_header = head == "value" or head.startswith("value,")
    if has_csv_header:
        reader = csv.DictReader(lines)
        for row in reader:
            value = (row.get("value") or "").strip()
            if not value:
                continue
            t = (row.get("type") or "").strip() or None
            yield value, t
    else:
        for line in lines:
            v = line.strip()
            if not v or v.startswith("#"):
                continue
            yield v, None


def ingest_file(path: Path, db_path: Path | None = None) -> dict:
    inserted = skipped = 0
    with connect(db_path) as conn, transaction(conn):
        for value, declared_type in _iter_rows(path):
            input_type = declared_type or classify_input(value)
            biz = Business(input_value=value, input_type=input_type)
            if input_type == "maps_url":
                parsed = parse_maps_url(value)
                biz.place_fingerprint = parsed["place_fingerprint"]
                biz.google_kg_id = parsed["google_kg_id"]
                biz.latitude = parsed["latitude"]
                biz.longitude = parsed["longitude"]
                biz.canonical_url = value
            elif input_type == "place_id":
                if value.startswith("/g/"):
                    biz.google_kg_id = value
                else:
                    biz.place_fingerprint = value
            row_id = insert_business(conn, biz)
            if row_id is None:
                skipped += 1
            else:
                inserted += 1
    return {"inserted": inserted, "skipped": skipped}
