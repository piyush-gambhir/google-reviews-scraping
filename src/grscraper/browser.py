import logging
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import config, stealth

log = logging.getLogger(__name__)


@contextmanager
def browser_context(headless: bool = True, profile_dir: Path | None = None):
    """Yield a Playwright persistent BrowserContext + page factory.

    Persistent profile keeps cookies between runs so we look like a returning
    user. `profile_dir` overrides it so a caller can retry a business on a
    profile Google has not seen; the runner uses a throwaway directory there
    because the reviews-pane bucket below is sticky per user_data_dir.

    Detection matters more than it looks. Google's usual response to an
    automated client is not a CAPTCHA — it serves the "limited view" panel,
    which renders the place with rating, address and hours but withholds the
    reviews tab and every review card, so a naive run reports success having
    scraped nothing. `reviews.is_limited_view` identifies it by name.

    What actually moves the needle, measured against a live listing rather than
    assumed:

    * The draw is made when the CONTEXT is created and never re-rolls inside it
      — reloads and new pages in a degraded context stay degraded. Only a fresh
      context draws again, which is why `runner` retries per business with a new
      context instead of retrying the page.
    * Headed made no difference: 3/5 headed vs 3/5 headless over interleaved
      trials. Do not reach for `GRS_HEADED` expecting it to fix withholding.
    * Google's own copy attributes limited view to "unusual traffic" on the
      network, and per-session yield decayed (45 -> 10 -> 5 preloaded reviews)
      as request volume rose. Pacing is worth more than fingerprint tweaking.

    Knobs, all switchable via env:

    * `GRS_BROWSER_CHANNEL` (default "chromium") — Playwright >= 1.49 resolves
      `headless=True` to a separate `chromium_headless_shell` binary, which is
      easier to fingerprint. "chromium" selects the full browser in
      new-headless mode.
    * `GRS_HEADED` — run headed. Needs an X server in a container; the image
      wraps the entrypoint in `xvfb-run` when this is set.
    * `GRS_STEALTH` (default on) — Chrome client-hint headers plus JS patches
      for the automation signals headless fails. Note these headers are applied
      context-wide, so only headers valid on every request may go in them; see
      `stealth.client_hint_headers`.
    """
    profile = profile_dir or config.BROWSER_PROFILE
    profile.mkdir(parents=True, exist_ok=True)
    if config.HEADED:
        headless = False

    launch_kwargs = dict(
        user_data_dir=str(profile),
        headless=headless,
        viewport=config.VIEWPORT,
        locale="en-US",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    if config.BROWSER_CHANNEL:
        launch_kwargs["channel"] = config.BROWSER_CHANNEL
    if config.TIMEZONE:
        launch_kwargs["timezone_id"] = config.TIMEZONE
    # Only override the UA when asked. A pinned string drifts out of sync with
    # the bundled browser, and the mismatch is itself a fingerprinting signal.
    if config.USER_AGENT:
        launch_kwargs["user_agent"] = config.USER_AGENT

    with sync_playwright() as p:
        context: BrowserContext = p.chromium.launch_persistent_context(**launch_kwargs)
        try:
            _apply_stealth(context)
            log.info(
                "browser: channel=%s headless=%s stealth=%s",
                config.BROWSER_CHANNEL or "default", headless, config.STEALTH,
            )
            yield context
        finally:
            context.close()


def _apply_stealth(context: BrowserContext) -> None:
    """Align headers and the JS surface with a real Chrome. Best effort."""
    if not config.STEALTH:
        # Still send a sane Accept-Language so results aren't localised oddly.
        context.set_extra_http_headers({"Accept-Language": config.ACCEPT_LANGUAGE})
        return
    try:
        probe = context.new_page()
        ua = probe.evaluate("navigator.userAgent")
        probe.close()
        context.set_extra_http_headers(stealth.client_hint_headers(ua))
        context.add_init_script(stealth.INIT_SCRIPT)
    except Exception as e:  # noqa: BLE001 - masking is optional, never fatal
        log.warning("stealth setup skipped: %r", e)
        context.set_extra_http_headers({"Accept-Language": config.ACCEPT_LANGUAGE})


def new_page(context: BrowserContext) -> Page:
    page = context.new_page()
    page.set_default_timeout(30_000)
    return page


def is_captcha(page: Page) -> bool:
    from .selectors import CAPTCHA_URL_FRAGMENT
    return CAPTCHA_URL_FRAGMENT in (page.url or "")
