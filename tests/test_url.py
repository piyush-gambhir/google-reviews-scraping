from grscraper.url import (
    cid_from_fingerprint,
    classify_input,
    maps_place_by_id_url,
    maps_search_url,
    parse_maps_url,
)

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


def test_cid_from_fingerprint():
    # the second half of the hex fingerprint is the CID
    assert cid_from_fingerprint("0x1234567890abcdef:0xfedcba0987654321") == 0xFEDCBA0987654321
    assert cid_from_fingerprint("not a fingerprint") is None
    assert cid_from_fingerprint("/g/11examplekg") is None
    assert cid_from_fingerprint("") is None


def test_place_by_id_url_uses_cid_for_fingerprints():
    """Only the cid form resolves — verified against a live listing.

    `?q=place_id:0x…` and `query_place_id=0x…` are treated as literal search
    text; `query_place_id` expects a `ChIJ…` Places id, not the hex form.
    """
    url = maps_place_by_id_url("0x1234567890abcdef:0xfedcba0987654321")
    assert url == f"https://www.google.com/maps?cid={0xFEDCBA0987654321}"
    assert "place_id:" not in url
    assert "query_place_id" not in url


def test_place_by_id_url_falls_back_to_search_for_kg_ids():
    # Knowledge Graph ids have no reliable direct URL; search is best-effort.
    url = maps_place_by_id_url("/g/11examplekg")
    assert url.startswith("https://www.google.com/maps/search/")
