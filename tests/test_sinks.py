import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from grscraper import sinks

PAYLOAD = {"schema_version": "1.0", "businesses": []}


def test_parse_sinks_splits_and_trims():
    assert sinks.parse_sinks(" -, file:///tmp/a.json ,") == ["-", "file:///tmp/a.json"]
    assert sinks.parse_sinks("") == []


def test_file_sink_accepts_bare_path(tmp_path):
    out = tmp_path / "nested" / "result.json"
    assert sinks.deliver_one(PAYLOAD, str(out)) == str(out)
    assert json.loads(out.read_text()) == PAYLOAD


def test_file_sink_accepts_file_uri(tmp_path):
    out = tmp_path / "result.json"
    sinks.deliver_one(PAYLOAD, f"file://{out}")
    assert json.loads(out.read_text()) == PAYLOAD


def test_stdout_sink(capsys):
    assert sinks.deliver_one(PAYLOAD, "-") == "stdout"
    assert json.loads(capsys.readouterr().out) == PAYLOAD


def test_unsupported_scheme_raises():
    with pytest.raises(sinks.SinkError, match="unsupported sink scheme"):
        sinks.deliver_one(PAYLOAD, "ftp://host/path")


def test_malformed_s3_uri_raises_before_importing_boto(monkeypatch):
    boto3 = pytest.importorskip("boto3")  # noqa: F841 - only to skip when absent
    with pytest.raises(sinks.SinkError, match="malformed s3 URI"):
        sinks.deliver_one(PAYLOAD, "s3://bucket-only")


class _Recorder(BaseHTTPRequestHandler):
    received: list[dict] = []
    headers_seen: list[dict] = []
    status = 200

    def do_POST(self):  # noqa: N802 - stdlib hook
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).received.append(json.loads(body))
        type(self).headers_seen.append(dict(self.headers))
        self.send_response(type(self).status)
        self.end_headers()

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture
def http_sink():
    _Recorder.received = []
    _Recorder.headers_seen = []
    _Recorder.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/ingest"
    server.shutdown()
    server.server_close()


def test_http_sink_posts_json(http_sink):
    result = sinks.deliver_one(PAYLOAD, http_sink)
    assert "HTTP 200" in result
    assert _Recorder.received == [PAYLOAD]
    assert _Recorder.headers_seen[0]["Content-Type"] == "application/json"


def test_http_sink_sends_bearer_token(http_sink, monkeypatch):
    monkeypatch.setattr(sinks.config, "SINK_HTTP_TOKEN", "s3cret")
    sinks.deliver_one(PAYLOAD, http_sink)
    assert _Recorder.headers_seen[0]["Authorization"] == "Bearer s3cret"


def test_http_sink_sends_extra_headers(http_sink, monkeypatch):
    monkeypatch.setattr(sinks.config, "SINK_HTTP_HEADERS", '{"X-Source": "grscraper"}')
    sinks.deliver_one(PAYLOAD, http_sink)
    assert _Recorder.headers_seen[0]["X-Source"] == "grscraper"


def test_http_sink_rejects_non_json_headers(http_sink, monkeypatch):
    monkeypatch.setattr(sinks.config, "SINK_HTTP_HEADERS", "not json")
    with pytest.raises(sinks.SinkError, match="not valid JSON"):
        sinks.deliver_one(PAYLOAD, http_sink)


def test_http_sink_raises_on_error_status(http_sink):
    _Recorder.status = 500
    with pytest.raises(sinks.SinkError, match="HTTP 500"):
        sinks.deliver_one(PAYLOAD, http_sink)


def test_deliver_continues_past_a_failing_sink(tmp_path, http_sink):
    """A broken webhook must not cost you the local copy of an expensive scrape."""
    _Recorder.status = 500
    out = tmp_path / "result.json"
    result = sinks.deliver(PAYLOAD, [http_sink, str(out)])
    assert len(result["errors"]) == 1
    assert result["delivered"] == [str(out)]
    assert json.loads(out.read_text()) == PAYLOAD
