from contextlib import contextmanager

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import config


@contextmanager
def browser_context(headless: bool = True):
    """Yield a Playwright persistent BrowserContext + page factory.

    Persistent profile keeps cookies between runs so we look like a returning
    user. Caller iterates many businesses against the same context but creates
    a fresh page per business via the yielded `new_page()` callable.

    `channel="chromium"` is load-bearing, not a preference. Playwright >= 1.49
    resolves plain `headless=True` to a separate `chromium_headless_shell`
    binary, and Google fingerprints it: the place panel renders (name, rating,
    address) but the reviews tab and every review card are withheld, so a run
    completes "successfully" having scraped nothing. Selecting the full
    Chromium build puts us in new-headless mode, which Google serves normally.
    Verified against a live listing: headless_shell => 0 review cards,
    channel="chromium" => cards present.
    """
    config.BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    launch_kwargs = dict(
        user_data_dir=str(config.BROWSER_PROFILE),
        channel="chromium",
        headless=headless,
        viewport=config.VIEWPORT,
        locale="en-US",
        extra_http_headers={"Accept-Language": config.ACCEPT_LANGUAGE},
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    # Only override the UA when asked. A pinned string drifts out of sync with
    # the bundled browser, and the mismatch is itself a fingerprinting signal.
    if config.USER_AGENT:
        launch_kwargs["user_agent"] = config.USER_AGENT

    with sync_playwright() as p:
        context: BrowserContext = p.chromium.launch_persistent_context(**launch_kwargs)
        try:
            yield context
        finally:
            context.close()


def new_page(context: BrowserContext) -> Page:
    page = context.new_page()
    page.set_default_timeout(30_000)
    return page


def is_captcha(page: Page) -> bool:
    from .selectors import CAPTCHA_URL_FRAGMENT
    return CAPTCHA_URL_FRAGMENT in (page.url or "")
