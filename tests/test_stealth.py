from grscraper.stealth import chrome_major, client_hint_headers

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.7922.34 Safari/537.36")


def test_chrome_major_extracts_version():
    assert chrome_major(UA) == "151"
    assert chrome_major("not a ua") is None
    assert chrome_major("") is None


def test_client_hints_match_the_running_browser():
    """Sec-CH-UA must agree with the UA — a mismatch is itself a signal."""
    h = client_hint_headers(UA)
    assert '"151"' in h["Sec-CH-UA"]
    assert h["Sec-CH-UA-Mobile"] == "?0"
    assert h["Sec-CH-UA-Platform"] == '"macOS"'
    assert h["Accept-Language"] == "en-US,en;q=0.9"


def test_client_hints_omitted_when_version_unknown():
    # better to send no client hints than ones invented from nothing
    h = client_hint_headers("some non-chrome agent")
    assert "Sec-CH-UA" not in h
    assert "Accept" in h


def test_platform_is_overridable():
    h = client_hint_headers(UA, platform='"Linux"')
    assert h["Sec-CH-UA-Platform"] == '"Linux"'
