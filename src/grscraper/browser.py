import logging
from contextlib import contextmanager

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import config, stealth

log = logging.getLogger(__name__)


@contextmanager
def browser_context(headless: bool = True):
    """Yield a Playwright persistent BrowserContext + page factory.

    Persistent profile keeps cookies between runs so we look like a returning
    user. Caller iterates many businesses against the same context but creates
    a fresh page per business via the yielded `new_page()` callable.

    Detection matters more than it looks. Google's usual response to an
    automated client is not a CAPTCHA — it renders the place panel normally
    while withholding the reviews tab and every review card, so the run reports
    success having scraped nothing. Three knobs exist to fight that, all
    switchable via env so a deployment can A/B them (see docs/DEPLOY.md):

    * `GRS_BROWSER_CHANNEL` (default "chromium") — Playwright >= 1.49 resolves
      `headless=True` to a separate `chromium_headless_shell` binary, which is
      easier to fingerprint. "chromium" selects the full browser in
      new-headless mode.
    * `GRS_HEADED` — run headed. Needs an X server in a container; the image
      wraps the entrypoint in `xvfb-run` when this is set.
    * `GRS_STEALTH` (default on) — Chrome client-hint headers plus JS patches
      for the automation signals headless fails.
    """
    config.BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    if config.HEADED:
        headless = False

    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE),
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
