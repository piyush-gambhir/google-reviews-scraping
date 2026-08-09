import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GRS_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("GRS_DB_PATH", DATA_DIR / "scraper.db"))
BROWSER_PROFILE = Path(os.environ.get("GRS_BROWSER_PROFILE", DATA_DIR / "browser_profile"))
EXPORT_DIR = Path(os.environ.get("GRS_EXPORT_DIR", DATA_DIR / "exports"))

MAX_RETRIES = int(os.environ.get("GRS_MAX_RETRIES", "3"))

THROTTLE_BUSINESS_MIN_MS = int(os.environ.get("GRS_THROTTLE_BUSINESS_MIN_MS", "5000"))
THROTTLE_BUSINESS_MAX_MS = int(os.environ.get("GRS_THROTTLE_BUSINESS_MAX_MS", "15000"))
THROTTLE_SCROLL_MIN_MS = int(os.environ.get("GRS_THROTTLE_SCROLL_MIN_MS", "1500"))
THROTTLE_SCROLL_MAX_MS = int(os.environ.get("GRS_THROTTLE_SCROLL_MAX_MS", "2500"))
BUSINESS_TIMEOUT_S = int(os.environ.get("GRS_BUSINESS_TIMEOUT_S", "600"))

# Empty by default: use whatever UA the bundled browser reports. A pinned
# string goes stale as the browser updates, and a UA that disagrees with the
# engine is a fingerprinting signal in its own right. Override only if you have
# a reason to.
USER_AGENT = os.environ.get("GRS_USER_AGENT", "")
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
VIEWPORT = {"width": 1280, "height": 900}

# --- Anti-detection knobs -------------------------------------------------
# Google frequently withholds the reviews pane from automated clients without
# ever showing a CAPTCHA. These exist so a deployment can A/B what helps
# instead of guessing; see docs/DEPLOY.md.
#
# Playwright >= 1.49 resolves headless=True to a separate
# `chromium_headless_shell` binary. "chromium" selects the full browser in
# new-headless mode. Set empty to use Playwright's default.
BROWSER_CHANNEL = os.environ.get("GRS_BROWSER_CHANNEL", "chromium")

# Run headed. In a container this needs an X server — the image wraps the
# entrypoint in xvfb-run when this is set.
HEADED = os.environ.get("GRS_HEADED", "").lower() in ("1", "true", "yes")

# Client-hint headers + JS patches that mask automation signals.
STEALTH = os.environ.get("GRS_STEALTH", "1").lower() in ("1", "true", "yes")

# Overrides the browser's timezone; a mismatch against the exit IP is a signal.
TIMEZONE = os.environ.get("GRS_TIMEZONE", "")

SCRAPER_VERSION = "0.2.2"

# Version of the emitted result envelope (see schemas/scrape-result.v1.json).
# Bump the major only on a breaking change to the document shape.
SCHEMA_VERSION = "1.0"

# --- Deployment / one-shot sync -------------------------------------------
# Targets to scrape when running `grscraper sync` without explicit arguments.
# Newline- or semicolon-separated. Each entry is `value` or `value|type`.
TARGETS = os.environ.get("GRS_TARGETS", "")

# Comma-separated sink URIs the sync result is delivered to.
#   -                     stdout
#   file:///path/out.json local file (a bare path also works)
#   https://host/ingest   HTTP POST, JSON body
#   s3://bucket/key.json  requires the [s3] extra
#   gs://bucket/key.json  requires the [gcs] extra
SINKS = os.environ.get("GRS_SINKS", "-")

# Bearer token applied to every http(s) sink.
SINK_HTTP_TOKEN = os.environ.get("GRS_SINK_HTTP_TOKEN", "")
# Extra headers for http(s) sinks, as a JSON object.
SINK_HTTP_HEADERS = os.environ.get("GRS_SINK_HTTP_HEADERS", "")
SINK_HTTP_TIMEOUT_S = int(os.environ.get("GRS_SINK_HTTP_TIMEOUT_S", "60"))

# HTTP server mode. Cloud Run injects PORT.
PORT = int(os.environ.get("PORT", os.environ.get("GRS_PORT", "8080")))
# When set, `POST /scrape` requires `Authorization: Bearer <token>`.
SERVER_TOKEN = os.environ.get("GRS_SERVER_TOKEN", "")
