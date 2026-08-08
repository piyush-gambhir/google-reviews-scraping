"""Delivery targets for a sync result.

Sinks are addressed by URI so a deployment is configured entirely through
`GRS_SINKS` — no code change to move from a local file to a webhook to object
storage. Cloud SDKs are imported lazily and declared as optional extras, so the
base image stays at two runtime dependencies.
"""

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import config

log = logging.getLogger(__name__)


class SinkError(RuntimeError):
    """A sink could not accept the payload."""


def _encode(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _http_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.SINK_HTTP_HEADERS:
        try:
            extra = json.loads(config.SINK_HTTP_HEADERS)
        except json.JSONDecodeError as e:
            raise SinkError(f"GRS_SINK_HTTP_HEADERS is not valid JSON: {e}") from e
        if not isinstance(extra, dict):
            raise SinkError("GRS_SINK_HTTP_HEADERS must be a JSON object")
        headers.update({str(k): str(v) for k, v in extra.items()})
    if config.SINK_HTTP_TOKEN:
        headers["Authorization"] = f"Bearer {config.SINK_HTTP_TOKEN}"
    return headers


def _write_stdout(payload: dict, _uri: str) -> str:
    print(json.dumps(payload, ensure_ascii=False))
    return "stdout"


def _write_file(payload: dict, uri: str) -> str:
    if uri.startswith("file://"):
        path = Path(urlparse(uri).path)
    else:
        path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_encode(payload))
    return str(path)


def _write_http(payload: dict, uri: str) -> str:
    request = urllib.request.Request(
        uri, data=_encode(payload), headers=_http_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=config.SINK_HTTP_TIMEOUT_S) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001 - diagnostics only
            pass
        raise SinkError(f"{uri} returned HTTP {e.code}: {body}") from e
    except urllib.error.URLError as e:
        raise SinkError(f"{uri} unreachable: {e.reason}") from e
    return f"{uri} (HTTP {status})"


def _write_s3(payload: dict, uri: str) -> str:
    try:
        import boto3
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise SinkError("s3:// sink requires the [s3] extra (pip install grscraper[s3])") from e
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if not parsed.netloc or not key:
        raise SinkError(f"malformed s3 URI: {uri} (expected s3://bucket/key)")
    boto3.client("s3").put_object(
        Bucket=parsed.netloc, Key=key, Body=_encode(payload), ContentType="application/json"
    )
    return uri


def _write_gcs(payload: dict, uri: str) -> str:
    try:
        from google.cloud import storage
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise SinkError("gs:// sink requires the [gcs] extra (pip install grscraper[gcs])") from e
    parsed = urlparse(uri)
    key = parsed.path.lstrip("/")
    if not parsed.netloc or not key:
        raise SinkError(f"malformed gs URI: {uri} (expected gs://bucket/object)")
    blob = storage.Client().bucket(parsed.netloc).blob(key)
    blob.upload_from_string(_encode(payload), content_type="application/json")
    return uri


def parse_sinks(raw: str) -> list[str]:
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


def deliver_one(payload: dict, uri: str) -> str:
    if uri in ("-", "stdout"):
        return _write_stdout(payload, uri)
    scheme = urlparse(uri).scheme
    if scheme in ("http", "https"):
        return _write_http(payload, uri)
    if scheme == "s3":
        return _write_s3(payload, uri)
    if scheme == "gs":
        return _write_gcs(payload, uri)
    if scheme in ("", "file"):
        return _write_file(payload, uri)
    raise SinkError(f"unsupported sink scheme {scheme!r} in {uri!r}")


def deliver(payload: dict, uris: list[str]) -> dict:
    """Write the payload to every sink.

    Every sink is attempted even if an earlier one fails — a broken webhook
    should not cost you the local copy of an expensive scrape. Failures are
    collected and returned; the caller decides whether that is fatal.
    """
    delivered: list[str] = []
    errors: list[str] = []
    for uri in uris:
        try:
            delivered.append(deliver_one(payload, uri))
            log.info("delivered to %s", uri)
        except SinkError as e:
            errors.append(str(e))
            log.error("sink failed: %s", e)
    return {"delivered": delivered, "errors": errors}
