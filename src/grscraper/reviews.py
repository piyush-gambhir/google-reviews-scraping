import logging
import random
import time

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PWTimeout

from . import config
from . import selectors as sel
from .browser import is_captcha
from .resolver import CaptchaError

log = logging.getLogger(__name__)

# The reviews pane renders in well under a second when it renders at all.
REVIEWS_PANE_TIMEOUT_MS = 8000


def _scroll_jitter_ms() -> int:
    return random.randint(config.THROTTLE_SCROLL_MIN_MS, config.THROTTLE_SCROLL_MAX_MS)


class ReviewsPaneUnavailable(RuntimeError):
    """The place resolved but Maps never rendered a reviews pane.

    Distinct from "this business has no reviews": it means the panel came back
    in the cut-down form that carries only Overview and About tabs, so there is
    nothing to scroll and nothing to click.
    """


def is_limited_view(page: Page) -> bool:
    """True when Maps served the "limited view" panel instead of the full one.

    Measured against a live listing: every withheld pane carried this string and
    every good pane did not, so it is a reliable classifier rather than a hint.
    """
    try:
        return bool(
            page.evaluate(
                "(needle) => (document.body?.innerText || '').toLowerCase().includes(needle)",
                sel.LIMITED_VIEW_TEXT,
            )
        )
    except Exception:
        # A page that cannot be evaluated is a different failure; let the caller
        # report the missing pane rather than masking it as a limited view.
        return False


def _reviews_pane_ready(page: Page) -> bool:
    """True once the reviews list is reachable — a tab to click, or cards."""
    return bool(
        page.evaluate(
            """([tabSel, cardSel]) =>
                document.querySelectorAll(tabSel).length > 0 ||
                document.querySelectorAll(cardSel).length > 0""",
            [sel.REVIEWS_TAB, sel.REVIEW_CARD],
        )
    )


def _wait_for_reviews_pane(page: Page, timeout_ms: int = REVIEWS_PANE_TIMEOUT_MS) -> bool:
    """Poll for the reviews pane.

    The good panel materialises well under a second, so this is a short wait,
    not patience: measured against a live listing, a panel that comes back
    without a Reviews tab never grows one — 30s of waiting and three reloads
    all stayed in the cut-down form. Waiting longer only slows the failure down.
    """
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        if _reviews_pane_ready(page):
            return True
        page.wait_for_timeout(250)
    return _reviews_pane_ready(page)


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

    deadline = time.monotonic() + config.BUSINESS_TIMEOUT_S
    for _ in range(max_iterations):
        if is_captcha(page):
            raise CaptchaError("captcha while scrolling reviews")
        if time.monotonic() >= deadline:
            raise TimeoutError("review collection exceeded GRS_BUSINESS_TIMEOUT_S")
        page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (el) el.scrollTop = el.scrollHeight;
            }""",
            selector,
        )
        page.wait_for_timeout(_scroll_jitter_ms())
        if is_captcha(page):
            raise CaptchaError("captcha while scrolling reviews")
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


def collect_reviews_html(
    page: Page, expected: int | None = None, reviews_url: str | None = None
) -> tuple[str, int]:
    """Open the reviews list, scroll-load everything, expand 'See more', return HTML.

    `reviews_url` is the `!9m1!1b1` deep link from `url.maps_reviews_url`. When
    given it is navigated to first, because the place page we arrive on is not
    always one that offers a Reviews tab: a URL copied out of Maps search
    results reliably renders the cut-down panel. The deep link lands on the
    reviews list with cards already in the DOM, and the tab click below stays as
    the fallback for inputs we could not build a deep link for.

    Returns (cards_container_html, count_of_cards).
    Raises ReviewsPaneUnavailable when no reviews pane ever appears.
    """
    if is_captcha(page):
        raise CaptchaError("captcha before reviews")
    if reviews_url:
        page.goto(reviews_url, wait_until="domcontentloaded")
        if is_captcha(page):
            raise CaptchaError("captcha on reviews deep link")
        _wait_for_reviews_pane(page)
    _open_reviews_tab(page)
    if is_captcha(page):
        raise CaptchaError("captcha after opening reviews tab")
    if not _wait_for_reviews_pane(page):
        if is_limited_view(page):
            raise ReviewsPaneUnavailable(
                "Google served its 'limited view' panel, which withholds reviews "
                "(triggered by network reputation, not by this place)"
            )
        raise ReviewsPaneUnavailable(
            "Maps rendered a panel with no reviews pane (Overview/About only)"
        )
    final_count = _scroll_load_all(page, target=expected)
    _expand_see_more(page)
    if is_captcha(page):
        raise CaptchaError("captcha after expanding reviews")
    html = page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            return el ? el.outerHTML : '';
        }""",
        sel.REVIEWS_SCROLL_CONTAINER,
    )
    return html, final_count
