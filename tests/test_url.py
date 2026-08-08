from grscraper.url import classify_input, maps_search_url, parse_maps_url

# Structurally a real Maps place URL; every identifier in it is synthetic.
CANONICAL_URL = (
    "https://www.google.com/maps/place/Acme+Coffee+Roasters/"
    "@12.3456789,98.7654321,17z/data=!4m8!3m7!1s0x1234567890abcdef:0xfedcba0987654321"
    "!8m2!3d12.3456789!4d98.7654321!9m1!1b1!16s%2Fg%2F11examplekg?entry=ttu"
)


def test_parse_canonical_url():
    parsed = parse_maps_url(CANONICAL_URL)
    assert parsed["place_fingerprint"] == "0x1234567890abcdef:0xfedcba0987654321"
    assert parsed["google_kg_id"] == "/g/11examplekg"
    assert parsed["latitude"] == 12.3456789
    assert parsed["longitude"] == 98.7654321


def test_parse_empty_url():
    assert parse_maps_url("")["place_fingerprint"] is None
    assert parse_maps_url("https://example.com")["place_fingerprint"] is None


def test_classify_input():
    assert classify_input("acme coffee roasters") == "name"
    assert classify_input("https://www.google.com/maps/place/foo") == "maps_url"
    assert classify_input("0x1234567890abcdef:0xfedcba0987654321") == "place_id"
    assert classify_input("/g/11examplekg") == "place_id"
    assert classify_input("https://example.com/maps/foo") == "name"


def test_maps_search_url_encoding():
    assert "acme%20coffee%20roasters" in maps_search_url("acme coffee roasters")
