import pytest

from grscraper import db
from grscraper.targets import ingest_targets, parse_targets


def test_parse_splits_on_newlines_and_semicolons():
    assert parse_targets("a\nb;c") == [("a", None), ("b", None), ("c", None)]


def test_parse_strips_blanks_and_comments():
    assert parse_targets("\n  \n# note\nreal target\n") == [("real target", None)]


def test_parse_explicit_type():
    assert parse_targets("acme coffee roasters|name") == [("acme coffee roasters", "name")]


def test_parse_pipe_in_value_keeps_last_segment_as_type():
    # rpartition means only the final `|type` is treated as the type
    assert parse_targets("a|b|name") == [("a|b", "name")]


def test_parse_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown target type"):
        parse_targets("foo|nonsense")


def test_parse_empty_is_empty():
    assert parse_targets("") == []
    assert parse_targets(None) == []


def test_ingest_targets_matches_file_ingest_semantics(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    db.init_db(db_path)
    monkeypatch.setattr(db.config, "DB_PATH", db_path)

    first = ingest_targets(parse_targets("alpha\nbeta"), db_path=db_path)
    assert first == {"inserted": 2, "skipped": 0}

    # re-running is a no-op, which is what makes a scheduled sync safe
    second = ingest_targets(parse_targets("alpha\nbeta"), db_path=db_path)
    assert second == {"inserted": 0, "skipped": 2}


def test_ingest_targets_classifies_place_id(tmp_path):
    db_path = tmp_path / "t.db"
    db.init_db(db_path)
    ingest_targets(parse_targets("/g/11examplekg"), db_path=db_path)
    with db.connect(db_path) as conn:
        row = conn.execute("SELECT input_type, google_kg_id FROM businesses").fetchone()
    assert row["input_type"] == "place_id"
    assert row["google_kg_id"] == "/g/11examplekg"


def test_ingest_targets_empty_list_is_noop(tmp_path):
    db_path = tmp_path / "t.db"
    db.init_db(db_path)
    assert ingest_targets([], db_path=db_path) == {"inserted": 0, "skipped": 0}
