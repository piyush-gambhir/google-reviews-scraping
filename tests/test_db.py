from grscraper import db
from grscraper.models import Business, Review


def test_init_and_insert(tmp_path, monkeypatch):
    p = tmp_path / "test.db"
    db.init_db(p)
    with db.connect(p) as conn:
        assert db.insert_business(conn, Business(input_value="foo", input_type="name")) == 1
        assert db.insert_business(conn, Business(input_value="foo", input_type="name")) is None
        assert db.insert_business(conn, Business(input_value="bar", input_type="name")) == 2
        counts = db.status_counts(conn)
        assert counts == {"queued": 2}


def test_upsert_review_dedup(tmp_path):
    p = tmp_path / "test.db"
    db.init_db(p)
    with db.connect(p) as conn:
        bid = db.insert_business(conn, Business(input_value="x", input_type="name"))
        r = Review(review_id="abc", business_id=bid, rating=5)
        assert db.upsert_review(conn, r) is True
        assert db.upsert_review(conn, r) is False


def test_fetch_next_filters_by_status_and_retries(tmp_path):
    p = tmp_path / "test.db"
    db.init_db(p)
    with db.connect(p) as conn:
        a = db.insert_business(conn, Business(input_value="a", input_type="name"))
        b = db.insert_business(conn, Business(input_value="b", input_type="name"))
        c = db.insert_business(conn, Business(input_value="c", input_type="name"))
        conn.commit()
        # mark `b` done, `c` failed too many times
        conn.execute("UPDATE businesses SET status='done' WHERE id=?", (b,))
        conn.execute("UPDATE businesses SET status='failed', retry_count=10 WHERE id=?", (c,))
        conn.commit()
        rows = db.fetch_next_businesses(conn, limit=10, max_retries=3)
        assert [r.id for r in rows] == [a]
