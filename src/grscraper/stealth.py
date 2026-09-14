"""Automation-fingerprint masking.

Google does not always CAPTCHA an automated client. The commoner response is
quieter: the place panel renders normally while the reviews tab and every
review card are withheld, so a run "succeeds" having scraped nothing.

Nothing here is exotic — it aligns the headers and JS surface with what a real
Chrome sends, so we stop failing checks a normal browser passes. It is not a
guarantee, and detection changes; treat it as reducing the odds, not removing
them. Everything is switchable so a deployment can A/B what actually helps.
"""

import re

_UA_MAJOR = re.compile(r"Chrome/(\d+)")


def chrome_major(user_agent: str) -> str | None:
    m = _UA_MAJOR.search(user_agent or "")
    return m.group(1) if m else None


def client_hint_headers(user_agent: str, platform: str = '"macOS"') -> dict[str, str]:
    """Build Sec-CH-UA headers consistent with the running browser.

    Real Chrome always sends these. Sending none — or sending a version that
    disagrees with the User-Agent — is itself a signal, which is why they are
    derived from the live UA rather than hardcoded.
    """
    major = chrome_major(user_agent)
    # Only headers that are valid on EVERY request may go in here: Playwright
    # applies them context-wide, to subresources and XHR as well as navigations.
    # Navigation-only headers are actively harmful, and both failures are silent:
    #   * Sec-Fetch-* / Upgrade-Insecure-Requests are browser-controlled per
    #     request. Forcing `Sec-Fetch-Dest: document` onto a subresource makes
    #     Chromium reject it with net::ERR_INVALID_ARGUMENT — Maps' own scripts
    #     fail to load and the app renders a blank body.
    #   * A document `Accept: text/html,...` on Maps' review XHRs makes Google
    #     answer them with HTML, so the panel renders with the reviews tab and
    #     every review card missing. That is the "withheld reviews" symptom this
    #     module was written to defeat; it was causing it.
    headers = {
        "Accept-Language": "en-US,en;q=0.9",
    }
    if major:
        headers["Sec-CH-UA"] = (
            f'"Chromium";v="{major}", "Not(A:Brand";v="24", "Google Chrome";v="{major}"'
        )
        headers["Sec-CH-UA-Mobile"] = "?0"
        headers["Sec-CH-UA-Platform"] = platform
    return headers


# Runs before any page script. Each patch corresponds to a check that headless
# Chromium fails and headed Chrome passes.
INIT_SCRIPT = """
// navigator.webdriver is the single most-checked automation flag.
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Headless reports an empty plugin/mimeType list; real Chrome never does.
if (!navigator.plugins || navigator.plugins.length === 0) {
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            {name: 'PDF Viewer', filename: 'internal-pdf-viewer'},
            {name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer'},
            {name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer'},
        ],
    });
}

// languages must agree with Accept-Language.
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});

// window.chrome exists in real Chrome and is missing in bare Chromium builds.
if (!window.chrome) {
    window.chrome = {runtime: {}, loadTimes: () => {}, csi: () => {}};
}

// Headless resolves Notification.permission inconsistently with the Permissions API.
if (window.navigator.permissions && navigator.permissions.query) {
    const original = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (params) =>
        params && params.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : original(params);
}

// SwiftShader gives away software rendering; report a plausible GPU instead.
try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (p) {
        if (p === 37445) return 'Intel Inc.';                 // UNMASKED_VENDOR_WEBGL
        if (p === 37446) return 'Intel Iris OpenGL Engine';   // UNMASKED_RENDERER_WEBGL
        return getParameter.apply(this, [p]);
    };
} catch (e) { /* no WebGL in this context */ }
"""
