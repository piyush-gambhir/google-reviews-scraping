import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import pytest

from grscraper import config, server
from grscraper.locking import ScrapeBusyError
from grscraper.request import ScrapeRequest


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(config, "SERVER_TOKEN", "test-token")
    monkeypatch.setattr(config, "ALLOW_UNAUTHENTICATED", False)
    monkeypatch.setattr(config, "SINKS", "https://example.test/approved")
    execute = Mock(return_value={"exit_code": 0, "reviews": 2})
    monkeypatch.setattr(ScrapeRequest, "execute", execute)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def request(body=None, *, method="POST", path="/scrape", headers=None, raw=None):
        connection = http.client.HTTPConnection(*httpd.server_address, timeout=3)
        try:
            connection.request(
                method,
                path,
                raw if raw is not None else json.dumps(body or {}),
                headers=headers
                if headers is not None
                else {
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    yield request, execute
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=3)


def test_health_and_authenticated_scrape(api):
    call, execute = api
    assert call(method="GET", path="/healthz", headers={})[0] == 200
    assert call({"targets": ["coffee"], "limit": 1})[0] == 200
    execute.assert_called_once()


def test_auth_fail_closed(api, monkeypatch):
    call, execute = api
    assert call(headers={})[0] == 401
    monkeypatch.setattr(config, "SERVER_TOKEN", "")
    assert call()[0] == 401
    monkeypatch.setattr(config, "ALLOW_UNAUTHENTICATED", True)
    assert call()[0] == 200
    assert execute.call_count == 1


@pytest.mark.parametrize(
    "body",
    [
        {"limit": -1},
        {"limit": True},
        {"limit": "2"},
        {"limit": 0},
        {"targets": [12]},
        {"targets": {}},
        {"inline_result": "false"},
        {"sinks": ["/tmp/overwrite.json"]},
        {"sinks": ["http://127.0.0.1/internal"]},
        {"targets": ["https://www.google.com.evil.test/maps/abc|maps_url"]},
        {"unknown": True},
        {"refresh": "false"},
    ],
)
def test_invalid_request_never_executes(api, body):
    call, execute = api
    assert call(body)[0] == 400
    execute.assert_not_called()


def test_rejects_body_before_reading_when_oversized(api):
    call, execute = api
    assert (
        call(
            raw=b"",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Length": str(server.MAX_BODY_BYTES + 1),
            },
        )[0]
        == 413
    )
    execute.assert_not_called()


def test_rejects_negative_content_length(api):
    call, execute = api
    assert (
        call(raw=b"", headers={"Authorization": "Bearer test-token", "Content-Length": "-1"})[0]
        == 400
    )
    execute.assert_not_called()


def test_invalid_utf8_returns_400(api):
    call, execute = api
    assert call(raw=b"\xff")[0] == 400
    execute.assert_not_called()


def test_errors_do_not_expose_exception_details_and_release_lock(api):
    call, execute = api
    execute.side_effect = RuntimeError("SECRET path or credential")
    status, body = call()
    assert status == 500 and "SECRET" not in json.dumps(body)
    execute.side_effect = None
    assert call()[0] == 200


def test_concurrent_request_returns_conflict(api):
    call, execute = api
    with server._scrape_lock:
        assert call()[0] == 409
    execute.assert_not_called()


def test_process_lock_conflict_returns_409(api):
    call, execute = api
    execute.side_effect = ScrapeBusyError()
    assert call()[0] == 409


def test_lambda_uses_shared_validation(monkeypatch):
    from grscraper import awslambda

    execute = Mock(return_value={"exit_code": 0})
    monkeypatch.setattr(ScrapeRequest, "execute", execute)
    with pytest.raises(ValueError):
        awslambda.handler({"limit": False})
    execute.assert_not_called()
    assert awslambda.handler({"limit": 2}) == {"exit_code": 0}


def test_request_body_timeout(api, monkeypatch):
    call, execute = api
    monkeypatch.setattr(server.Handler, "timeout", 0.1)
    assert (
        call(
            raw=b"",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Type": "application/json",
                "Content-Length": "20",
            },
        )[0]
        == 408
    )
    execute.assert_not_called()


def test_openapi_contract_matches_real_empty_sync(tmp_path, monkeypatch):
    from pathlib import Path

    import jsonschema
    from referencing import Registry, Resource

    from grscraper.sync import sync

    root = Path(__file__).resolve().parents[1]
    spec = json.loads((root / "schemas/openapi.json").read_text())
    output = json.loads((root / "schemas/scrape-result.v1.json").read_text())
    output.pop("$id", None)
    registry = Registry().with_resource("scrape-result.v1.json", Resource.from_contents(output))
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "scraper.db")
    monkeypatch.setattr(config, "TARGETS", "")
    result = sync(raw_targets="", sink_uris=[])
    result["result"] = result.pop("payload")
    jsonschema.Draft202012Validator(
        spec["components"]["schemas"]["SyncResult"], registry=registry
    ).validate(result)
    request_schema = spec["components"]["schemas"]["ScrapeRequest"]
    jsonschema.Draft202012Validator.check_schema(request_schema)
    assert not jsonschema.Draft202012Validator(request_schema).is_valid({"limit": True})
