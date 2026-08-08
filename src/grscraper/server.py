"""Minimal HTTP mode, for platforms that expect a listening port.

Cloud Run *services*, Knative and most PaaS health-check a port; Cloud Run
*jobs* and Lambda do not. This exists so one image covers both. It is stdlib
only — a scraper should not carry a web framework to answer three routes.

`POST /scrape` runs synchronously and can take minutes. Raise the platform's
request timeout accordingly (Cloud Run allows up to 60 minutes), or prefer a
job/`sync` deployment, which is the better fit for scheduled work.
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config

log = logging.getLogger(__name__)

# One browser profile, one SQLite file: concurrent scrapes would corrupt both.
_scrape_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = f"grscraper/{config.SCRAPER_VERSION}"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - stdlib hook
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: dict) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        if not config.SERVER_TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {config.SERVER_TOKEN}"

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        if self.path in ("/healthz", "/readyz", "/"):
            self._send(200, {
                "status": "ok",
                "scraper_version": config.SCRAPER_VERSION,
                "schema_version": config.SCHEMA_VERSION,
                "busy": _scrape_lock.locked(),
            })
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook
        if self.path != "/scrape":
            self._send(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, {"error": "bad Content-Length"})
            return

        body: dict = {}
        if length:
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as e:
                self._send(400, {"error": f"invalid JSON body: {e}"})
                return
        if not isinstance(body, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return

        if not _scrape_lock.acquire(blocking=False):
            self._send(409, {"error": "a scrape is already running"})
            return
        try:
            from .sync import sync

            targets = body.get("targets")
            if isinstance(targets, list):
                targets = "\n".join(str(t) for t in targets)
            sinks = body.get("sinks")
            if isinstance(sinks, str):
                sinks = [s.strip() for s in sinks.split(",") if s.strip()]

            result = sync(
                raw_targets=targets,
                sink_uris=sinks,
                limit=body.get("limit"),
                include_internal=bool(body.get("include_internal", False)),
            )
            payload = result.pop("payload")
            if body.get("inline_result"):
                result["result"] = payload
            self._send(200 if result["exit_code"] == 0 else 502, result)
        except Exception as e:  # noqa: BLE001 - surface any failure as 500
            log.exception("scrape failed")
            self._send(500, {"error": repr(e)})
        finally:
            _scrape_lock.release()


def serve(port: int | None = None) -> int:
    bind = ("0.0.0.0", port or config.PORT)  # noqa: S104 - containers bind all interfaces
    httpd = ThreadingHTTPServer(bind, Handler)
    log.warning("grscraper serving on http://%s:%d", *bind)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
