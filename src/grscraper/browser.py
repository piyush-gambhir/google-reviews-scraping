from contextlib import contextmanager

from playwright.sync_api import BrowserContext, Page, sync_playwright

from . import config


@contextmanager
def browser_context(headless: bool = True):
    """Yield a Playwright persistent BrowserContext + page factory.

    Persistent profile keeps cookies between runs so we look like a returning
    user. Caller iterates many businesses against the same context but creates
    a fresh page per business via the yielded `new_page()` callable.
    """
    config.BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context: BrowserContext = p.chromium.launch_persistent_context(
            user_data_dir=str(config.BROWSER_PROFILE),
            headless=headless,
            user_agent=config.USER_AGENT,
            viewport=config.VIEWPORT,
            locale="en-US",
            extra_http_headers={"Accept-Language": config.ACCEPT_LANGUAGE},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
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
