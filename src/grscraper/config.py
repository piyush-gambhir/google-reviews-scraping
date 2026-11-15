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





USER_AGENT = os.environ.get("GRS_USER_AGENT", "")
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
VIEWPORT = {"width": 1280, "height": 900}









BROWSER_CHANNEL = os.environ.get("GRS_BROWSER_CHANNEL", "chromium")



HEADED = os.environ.get("GRS_HEADED", "").lower() in ("1", "true", "yes")


STEALTH = os.environ.get("GRS_STEALTH", "1").lower() in ("1", "true", "yes")


TIMEZONE = os.environ.get("GRS_TIMEZONE", "")


def _pane_attempts() -> int:
    """Attempts per business, each on its own browser context.

    Whether Maps serves the full place panel or the cut-down Overview/About one
    is decided when the browser context is created and never re-rolls inside it:
    reloads and new pages in the same context stay degraded, only a brand-new
    context draws again. So this is the one retry that helps. A bad value falls
    back to a single attempt rather than aborting a scheduled run.
    """
    try:
        value = int(os.environ.get("GRS_PANE_ATTEMPTS", "3"))
    except ValueError:
        return 1
    return value if value >= 1 else 1


PANE_ATTEMPTS = _pane_attempts()

SCRAPER_VERSION = "0.2.3"



SCHEMA_VERSION = "1.0"




TARGETS = os.environ.get("GRS_TARGETS", "")







SINKS = os.environ.get("GRS_SINKS", "-")


SINK_HTTP_TOKEN = os.environ.get("GRS_SINK_HTTP_TOKEN", "")

SINK_HTTP_HEADERS = os.environ.get("GRS_SINK_HTTP_HEADERS", "")
SINK_HTTP_TIMEOUT_S = int(os.environ.get("GRS_SINK_HTTP_TIMEOUT_S", "60"))


PORT = int(os.environ.get("PORT", os.environ.get("GRS_PORT", "8080")))

SERVER_TOKEN = os.environ.get("GRS_SERVER_TOKEN", "")

ALLOW_UNAUTHENTICATED = os.environ.get("GRS_ALLOW_UNAUTHENTICATED", "").lower() in (
    "1",
    "true",
    "yes",
)
