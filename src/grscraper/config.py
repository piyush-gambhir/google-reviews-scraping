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

USER_AGENT = os.environ.get(
    "GRS_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)
ACCEPT_LANGUAGE = "en-US,en;q=0.9"
VIEWPORT = {"width": 1280, "height": 900}

SCRAPER_VERSION = "0.1.0"
