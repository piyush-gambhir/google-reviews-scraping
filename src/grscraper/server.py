"""Small synchronous HTTP adapter for a single operator-owned queue.

Use behind an authenticated reverse proxy with request/concurrency limits.
See docs/API.md for the contract and docs/DEPLOY.md for deployment constraints.
"""

import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import config
from .locking import ScrapeBusyError
from .request import ScrapeRequest

log = logging.getLogger(__name__)
_scrape_lock = threading.Lock()
MAX_BODY_BYTES = 1_048_576


class Handler(BaseHTTPRequestHandler):
    server_version = f"grscraper/{config.SCRAPER_VERSION}"
    timeout = 30  # socket reads only; does not terminate browser work

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            log.info("client disconnected before receiving response")

    def _authorized(self) -> bool:
        if not config.SERVER_TOKEN:
            return config.ALLOW_UNAUTHENTICATED
        return hmac.compare_digest(
            self.headers.get("Authorization", "").encode(),
            f"Bearer {config.SERVER_TOKEN}".encode(),
        )

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        if urlsplit(self.path).path in ("/healthz", "/readyz", "/"):
            self._send(
                200,
                {
                    "status": "ok",
                    "scraper_version": config.SCRAPER_VERSION,
                    "schema_version": config.SCHEMA_VERSION,
                    "busy": _scrape_lock.locked(),
                },
            )
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        if urlsplit(self.path).path != "/scrape":
            self._send(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        if self.headers.get("Transfer-Encoding"):
            self._send(400, {"error": "Transfer-Encoding is not supported"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (
            len(lengths) > 1
            or (lengths and not lengths[0].isascii())
            or (lengths and not lengths[0].isdigit())
        ):
            self._send(400, {"error": "bad Content-Length"})
            return
        # Compare length text before int conversion (also bounds huge integers).
        length_text = lengths[0].lstrip("0") if lengths else ""
        if len(length_text) > 7:
            self._send(413, {"error": "request body exceeds 1 MiB"})
            return
        length = int(length_text or "0")
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": "request body exceeds 1 MiB"})
            return
        if length and self.headers.get_content_type() != "application/json":
            self._send(415, {"error": "Content-Type must be application/json"})
            return
        try:
            raw = self.rfile.read(length) if length else b"{}"
            if length and len(raw) != length:
                raise ValueError("incomplete body")
            body = json.loads(raw.decode("utf-8"))
            request = ScrapeRequest.parse(body, restrict_sinks=True)
        except TimeoutError:
            self._send(408, {"error": "request body timed out"})
            return
        except (ValueError, RecursionError):
            self._send(400, {"error": "invalid request; see docs/API.md"})
            return
        if not _scrape_lock.acquire(blocking=False):
            self._send(409, {"error": "a scrape is already running"})
            return
        try:
            result = request.execute()
            self._send(200 if result["exit_code"] == 0 else 502, result)
        except ScrapeBusyError:
            self._send(409, {"error": "a scrape is already running"})
        except Exception:
            log.exception("scrape failed")
            self._send(500, {"error": "scrape failed; check server logs"})
        finally:
            _scrape_lock.release()


def serve(port: int | None = None) -> int:
    if not config.SERVER_TOKEN and not config.ALLOW_UNAUTHENTICATED:
        raise ValueError("set GRS_SERVER_TOKEN or explicitly set GRS_ALLOW_UNAUTHENTICATED=1")
    if not config.SERVER_TOKEN:
        log.warning("HTTP authentication disabled; use only behind trusted ingress")
    bind = ("0.0.0.0", config.PORT if port is None else port)
    httpd = ThreadingHTTPServer(bind, Handler)
    log.warning("grscraper serving on http://%s:%d", *httpd.server_address)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
