import json
import logging
import re
from urllib.parse import quote

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from . import selectors as sel
from .browser import is_captcha
from .models import Business
from .url import maps_search_url, parse_maps_url

log = logging.getLogger(__name__)


class CaptchaError(RuntimeError):
    pass


class ResolveError(RuntimeError):
    pass


def _wait_settle(page: Page, max_ms: int = 8000) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=max_ms)
    except PWTimeout:
        pass
    page.wait_for_timeout(800)


def _wait_for_place_url(page: Page, max_ms: int = 8000) -> bool:
    """Poll page.url for the /maps/place/ canonical pattern."""
    deadline_steps = max_ms // 250
    for _ in range(deadline_steps):
        if "/maps/place/" in (page.url or ""):
            return True
        page.wait_for_timeout(250)
    return "/maps/place/" in (page.url or "")


def _navigate_for_input(page: Page, biz: Business) -> None:
    if biz.input_type == "maps_url":
        url = biz.canonical_url or biz.input_value
    elif biz.input_type == "place_id":
        ident = biz.place_fingerprint or biz.google_kg_id or biz.input_value
        url = f"https://www.google.com/maps/place/?q=place_id:{quote(ident)}"
    else:
        url = maps_search_url(biz.input_value)
    page.goto(url, wait_until="domcontentloaded")
    _wait_settle(page)
    _wait_for_place_url(page)


def _maybe_pick_first_result(page: Page) -> None:
    """If we're still on a /maps/search/ list, click the first result."""
    if "/maps/place/" in page.url:
        return
    try:
        first = page.locator('a.hfpxzc').first
        if first.count() > 0:
            first.click(timeout=5000)
            _wait_settle(page)
    except PWTimeout:
        pass


def _text_or_none(page: Page, selector: str) -> str | None:
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            return None
        t = loc.inner_text(timeout=2000).strip()
        return t or None
    except PWTimeout:
        return None
    except Exception:
        return None


def _attr_or_none(page: Page, selector: str, attr: str) -> str | None:
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            return None
        v = loc.get_attribute(attr, timeout=2000)
        return v
    except PWTimeout:
        return None
    except Exception:
        return None


def _extract_review_count_from_block(text: str | None) -> int | None:
    """Parse '4.9(102)' or '4.9 (1,234)' style block text."""
    if not text:
        return None
    m = re.search(r"\(([\d,]+)\)", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def _extract_rating(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _scrape_hours(page: Page) -> str | None:
    try:
        rows = page.locator(sel.PLACE_HOURS_TABLE)
        n = rows.count()
        if n == 0:
            return None
        out: dict[str, str] = {}
        for i in range(n):
            row = rows.nth(i)
            day_loc = row.locator("td").nth(0)
            time_loc = row.locator("td").nth(1)
            day = day_loc.inner_text(timeout=1500).strip() if day_loc.count() else ""
            t = time_loc.inner_text(timeout=1500).strip() if time_loc.count() else ""
            if day:
                out[day] = t
        return json.dumps(out, ensure_ascii=False) if out else None
    except Exception:
        return None


def resolve(page: Page, biz: Business) -> Business:
    """Navigate to the canonical place page and pull metadata.

    Returns the updated Business (caller persists). Mutates `biz` in place.
    Raises CaptchaError on /sorry/ redirect, ResolveError on other failures.
    """
    _navigate_for_input(page, biz)
    if is_captcha(page):
        raise CaptchaError("captcha on resolve")
    _maybe_pick_first_result(page)
    if is_captcha(page):
        raise CaptchaError("captcha after picking first result")
    if "/maps/place/" not in page.url:
        raise ResolveError(f"did not reach a place page: {page.url}")

    biz.canonical_url = page.url
    parsed = parse_maps_url(page.url)
    biz.place_fingerprint = parsed["place_fingerprint"] or biz.place_fingerprint
    biz.google_kg_id = parsed["google_kg_id"] or biz.google_kg_id
    biz.latitude = parsed["latitude"] or biz.latitude
    biz.longitude = parsed["longitude"] or biz.longitude

    biz.name = _text_or_none(page, sel.PLACE_TITLE)
    biz.category = _text_or_none(page, sel.PLACE_CATEGORY)
    biz.address = _text_or_none(page, f"{sel.PLACE_ADDRESS} {sel.PLACE_ADDRESS_TEXT}")
    biz.phone = _attr_or_none(page, sel.PLACE_PHONE, "aria-label")
    if biz.phone:
        biz.phone = re.sub(r"^Phone:?\s*", "", biz.phone).strip() or biz.phone
    biz.website = _attr_or_none(page, sel.PLACE_WEBSITE, "href")
    biz.plus_code = _attr_or_none(page, sel.PLACE_PLUS_CODE, "aria-label")
    if biz.plus_code:
        biz.plus_code = re.sub(r"^Plus code:?\s*", "", biz.plus_code).strip() or biz.plus_code

    rating_block_text = _text_or_none(page, sel.PLACE_RATING_AND_COUNT_BLOCK)
    biz.overall_rating = _extract_rating(rating_block_text)
    biz.review_count = _extract_review_count_from_block(rating_block_text)

    biz.hours_json = _scrape_hours(page)

    biz.status = "resolved"
    biz.status_reason = None
    return biz
