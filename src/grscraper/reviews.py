import logging
import random

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from . import config
from . import selectors as sel
from .browser import is_captcha
from .resolver import CaptchaError

log = logging.getLogger(__name__)


def _scroll_jitter_ms() -> int:
    return random.randint(config.THROTTLE_SCROLL_MIN_MS, config.THROTTLE_SCROLL_MAX_MS)


def _open_reviews_tab(page: Page) -> None:
    tab = page.locator(sel.REVIEWS_TAB).first
    if tab.count() == 0:
        return
    try:
        tab.click(timeout=8000)
        page.wait_for_timeout(1500)
    except PWTimeout:
        log.warning("Reviews tab click timed out")


def _scroll_load_all(page: Page, target: int | None = None) -> int:
    """Scroll the reviews container until count stabilizes.

    Returns the final count of review cards present. Stops after 2 stable
    cycles or when count reaches `target`.
    """
    selector = sel.REVIEWS_SCROLL_CONTAINER
    last = 0
    stable = 0
    max_iterations = 1200

    for _ in range(max_iterations):
        page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (el) el.scrollTop = el.scrollHeight;
            }""",
            selector,
        )
        page.wait_for_timeout(_scroll_jitter_ms())
        count = page.evaluate(
            """(sel) => document.querySelectorAll(sel).length""",
            sel.REVIEW_CARD,
        )
        if target and count >= target:
            return count
        if count == last:
            stable += 1
            if stable >= 2:
                return count
        else:
            stable = 0
            last = count
    return last


def _expand_see_more(page: Page) -> None:
    """Click every visible 'See more' button so review_text contains full body."""
    page.evaluate(
        """(sel) => {
            document.querySelectorAll(sel).forEach((b) => {
                try { b.click(); } catch (e) {}
            });
        }""",
        sel.REVIEW_CARD_FIELDS["see_more_btn"],
    )
    page.wait_for_timeout(500)


def collect_reviews_html(page: Page, expected: int | None = None) -> tuple[str, int]:
    """Open Reviews tab, scroll-load everything, expand 'See more', return HTML.

    Returns (cards_container_html, count_of_cards).
    """
    if is_captcha(page):
        raise CaptchaError("captcha before reviews")
    _open_reviews_tab(page)
    if is_captcha(page):
        raise CaptchaError("captcha after opening reviews tab")
    final_count = _scroll_load_all(page, target=expected)
    _expand_see_more(page)
    html = page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            return el ? el.outerHTML : '';
        }""",
        sel.REVIEWS_SCROLL_CONTAINER,
    )
    return html, final_count
