"""Target resolution for containerised runs.

The file-based `ingest` command stays the ergonomic path for local use. A
container has no convenient place to put a CSV, so `sync` also accepts targets
inline — from argv or from `GRS_TARGETS` — and feeds them through the exact
same classification the file path uses.
"""

import re

from .db import connect, insert_business, transaction
from .models import Business
from .url import classify_input, parse_maps_url

_SPLIT = re.compile(r"[\n;]+")

VALID_TYPES = {"name", "maps_url", "place_id"}


def parse_targets(raw: str) -> list[tuple[str, str | None]]:
    """Split a raw target string into (value, declared_type) pairs.

    Entries are separated by newlines or semicolons. An entry may carry an
    explicit type after a pipe: `acme coffee roasters|name`. Blank entries and
    `#` comments are dropped.
    """
    out: list[tuple[str, str | None]] = []
    for chunk in _SPLIT.split(raw or ""):
        entry = chunk.strip()
        if not entry or entry.startswith("#"):
            continue
        if "|" in entry:
            value, _, declared = entry.rpartition("|")
            value = value.strip()
            declared = declared.strip().lower()
            if declared not in VALID_TYPES:
                raise ValueError(
                    f"unknown target type {declared!r} in {entry!r}; "
                    f"expected one of {sorted(VALID_TYPES)}"
                )
        else:
            value, declared = entry, None
        if not value:
            continue
        out.append((value, declared))
    return out


def ingest_targets(targets: list[tuple[str, str | None]], db_path=None) -> dict:
    """Enqueue parsed targets. Mirrors ingest.ingest_file's semantics."""
    inserted = skipped = 0
    if not targets:
        return {"inserted": 0, "skipped": 0}
    with connect(db_path) as conn, transaction(conn):
        for value, declared_type in targets:
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
            if insert_business(conn, biz) is None:
                skipped += 1
            else:
                inserted += 1
    return {"inserted": inserted, "skipped": skipped}
