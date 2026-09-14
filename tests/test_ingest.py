from grscraper import db
from grscraper.ingest import ingest_file


def test_ingest_csv_with_header(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "config", db.config)
    db_path = tmp_path / "x.db"
    db.init_db(db_path)
    inp = tmp_path / "in.csv"
    inp.write_text(
        "value,type\n"
        "acme coffee roasters,\n"
        # quoted: a Maps URL contains commas and would otherwise split columns
        '"https://www.google.com/maps/place/Foo/@1,2,17z/data=!1s0xab:0xcd!16s%2Fg%2Ftest",\n'
        "0xab:0xcd,place_id\n",
        encoding="utf-8",
    )
    result = ingest_file(inp, db_path=db_path)
    # Both maps_url and the explicit place_id share the place fingerprint, so one is dedup'd
    assert result["inserted"] >= 2

    with db.connect(db_path) as conn:
        rows = conn.execute("SELECT input_type FROM businesses").fetchall()
    types = sorted(r["input_type"] for r in rows)
    assert "name" in types
    assert "maps_url" in types or "place_id" in types


def test_ingest_newline_file(tmp_path):
    db_path = tmp_path / "x.db"
    db.init_db(db_path)
    inp = tmp_path / "in.txt"
    inp.write_text("# header comment\nfoo bar\nbaz quux\n\n", encoding="utf-8")
    result = ingest_file(inp, db_path=db_path)
    assert result["inserted"] == 2
    assert result["skipped"] == 0


def test_ingest_idempotent(tmp_path):
    db_path = tmp_path / "x.db"
    db.init_db(db_path)
    inp = tmp_path / "in.txt"
    inp.write_text("alpha\nbeta\n", encoding="utf-8")
    r1 = ingest_file(inp, db_path=db_path)
    r2 = ingest_file(inp, db_path=db_path)
    assert r1["inserted"] == 2
    assert r2["inserted"] == 0
    assert r2["skipped"] == 2


def test_rejects_unknown_declared_input_type(tmp_path):
    """A comma in a Maps URL splits an unquoted CSV row across both columns.

    The longitude lands in the `type` column and the URL arrives truncated.
    Accepting that silently scrapes the wrong place.
    """
    import pytest

    from grscraper.ingest import ingest_file

    csv = tmp_path / "bad.csv"
    csv.write_text(
        "value,type\n"
        "https://www.google.com/maps/place/Martin+Honda/@39.0710456,-76.3012658,9z\n"
    )
    with pytest.raises(ValueError, match="unknown input type"):
        ingest_file(csv, db_path=tmp_path / "t.db")


def test_chij_place_id_is_decoded_to_a_fingerprint(tmp_path):
    """A Places API id must reach the DB as hex — no Maps surface accepts ChIJ…"""
    from grscraper import db
    from grscraper.ingest import ingest_file

    db_path = tmp_path / "p.db"
    db.init_db(db_path)
    inp = tmp_path / "in.txt"
    inp.write_text("ChIJN1t_tDeuEmsRUsoyG83frY4\n", encoding="utf-8")

    assert ingest_file(inp, db_path=db_path)["inserted"] == 1
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT input_type, place_fingerprint FROM businesses"
        ).fetchone()
    assert row["input_type"] == "place_id"
    assert row["place_fingerprint"] == "0x6b12ae37b47f5b37:0x8eaddfcd1b32ca52"
