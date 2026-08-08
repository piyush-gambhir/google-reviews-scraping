import json
from pathlib import Path

import pytest

from grscraper import db, snapshot
from grscraper.models import Business, Review

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "scrape-result.v1.json"


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    db_path = tmp_path / "s.db"
    db.init_db(db_path)
    monkeypatch.setattr(db.config, "DB_PATH", db_path)
    with db.connect(db_path) as conn:
        bid = db.insert_business(
            conn, Business(input_value="acme coffee roasters", input_type="name")
        )
        conn.execute(
            "UPDATE businesses SET name=?, overall_rating=?, review_count=?, status='done'"
            " WHERE id=?",
            ("Acme Coffee Roasters", 4.8, 2, bid),
        )
        db.upsert_review(
            conn,
            Review(
                review_id="rev-1",
                business_id=bid,
                reviewer_name="A",
                rating=5,
                review_text="great",
                photo_urls=["https://example.test/a.jpg"],
                scraped_at="2026-08-08T00:00:00+00:00",
                scraper_version="0.2.0",
            ),
        )
        db.upsert_review(
            conn,
            Review(
                review_id="rev-2",
                business_id=bid,
                reviewer_name="B",
                rating=4,
                scraped_at="2026-08-08T00:00:00+00:00",
                scraper_version="0.2.0",
            ),
        )
        conn.commit()
    return db_path


def test_build_nests_reviews_under_business(seeded):
    doc = snapshot.build({"total": 1, "done": 1, "failed": 0, "blocked": False,
                          "reviews_added": 2})
    assert len(doc["businesses"]) == 1
    biz = doc["businesses"][0]
    assert biz["name"] == "Acme Coffee Roasters"
    assert [r["review_id"] for r in biz["reviews"]] == ["rev-1", "rev-2"]


def test_photo_urls_are_decoded_to_a_list(seeded):
    doc = snapshot.build()
    reviews = {r["review_id"]: r for r in doc["businesses"][0]["reviews"]}
    assert reviews["rev-1"]["photo_urls"] == ["https://example.test/a.jpg"]
    # absent photos become [] rather than null, so consumers can always iterate
    assert reviews["rev-2"]["photo_urls"] == []
    assert "photo_urls_json" not in reviews["rev-1"]


def test_internal_columns_are_dropped_by_default(seeded):
    biz = snapshot.build(include_internal=False)["businesses"][0]
    for column in ("status", "status_reason", "retry_count"):
        assert column not in biz

    biz = snapshot.build(include_internal=True)["businesses"][0]
    assert biz["status"] == "done"


def test_run_block_defaults_to_zeroes_without_a_run(seeded):
    doc = snapshot.build()
    assert doc["run"] == {
        "total": 0, "done": 0, "failed": 0, "blocked": False, "reviews_added": 0
    }


def test_only_done_filters_unfinished_businesses(seeded):
    with db.connect(seeded) as conn:
        db.insert_business(conn, Business(input_value="queued one", input_type="name"))
        conn.commit()

    assert len(snapshot.build()["businesses"]) == 2
    assert len(snapshot.build(only_done=True)["businesses"]) == 1


def test_document_validates_against_the_published_schema(seeded):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text())
    for include_internal in (True, False):
        doc = snapshot.build(
            {"total": 1, "done": 1, "failed": 0, "blocked": False, "reviews_added": 2},
            include_internal=include_internal,
        )
        jsonschema.validate(doc, schema)


def test_empty_store_still_produces_a_valid_document(tmp_path, monkeypatch):
    jsonschema = pytest.importorskip("jsonschema")
    db_path = tmp_path / "empty.db"
    db.init_db(db_path)
    monkeypatch.setattr(db.config, "DB_PATH", db_path)
    doc = snapshot.build()
    assert doc["businesses"] == []
    jsonschema.validate(doc, json.loads(SCHEMA_PATH.read_text()))
