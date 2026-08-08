import json

import pytest

from grscraper import cli, db


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point every config path at a temp dir so the CLI touches nothing real."""
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "scraper.db")
    monkeypatch.setattr(db.config, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(db.config, "TARGETS", "")
    monkeypatch.setattr(db.config, "SINKS", "-")
    return tmp_path


def test_sync_writes_only_the_payload_to_stdout(isolated, capsys):
    """`grscraper sync > out.json` must produce parseable JSON and nothing else.

    Regression: the run summary used to share stdout with the `-` sink, which
    appended log lines after the document and made the output invalid JSON.
    """
    assert cli.main(["sync", "--sink", "-"]) == 0
    captured = capsys.readouterr()

    doc = json.loads(captured.out)          # would raise "Extra data" before the fix
    assert doc["schema_version"] == "1.0"
    assert doc["businesses"] == []

    # the human summary is still emitted, just on the other stream
    assert "targets=0" in captured.err


def test_sync_to_a_file_sink_leaves_stdout_empty(isolated, capsys):
    out = isolated / "result.json"
    assert cli.main(["sync", "--sink", str(out)]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(out.read_text())["schema_version"] == "1.0"


def test_sync_returns_sink_failure_exit_code(isolated, capsys):
    # port 1 is reserved and refuses connections, so the sink cannot deliver
    assert cli.main(["sync", "--sink", "http://127.0.0.1:1/ingest"]) == 3
    assert "!!" in capsys.readouterr().err


def test_unknown_subcommand_exits_nonzero(isolated):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["nope"])
    assert excinfo.value.code != 0
