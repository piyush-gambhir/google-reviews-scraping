from grscraper.url import (
    cid_from_fingerprint,
    classify_input,
    fingerprint_from_place_id,
    maps_place_by_id_url,
    maps_reviews_url,
    maps_search_url,
    parse_maps_url,
    place_id_from_fingerprint,
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


def test_reviews_url_contains_the_show_reviews_flag():
    """`!9m1!1b1` is what makes Maps open the reviews list rather than Overview."""
    url = maps_reviews_url("0x89c7aa3edff67c63:0x3672dc0023b11b8f", 39.6873533, -75.741334)
    assert url is not None
    assert "!9m1!1b1" in url
    assert "0x89c7aa3edff67c63:0x3672dc0023b11b8f" in url
    # the @lat,lng,17z segment is required; without it Maps renders no place
    assert "/@39.6873533,-75.741334,17z/" in url
    assert url.endswith("?hl=en")


def test_reviews_url_needs_a_fingerprint_and_coordinates():
    fp = "0x89c7aa3edff67c63:0x3672dc0023b11b8f"
    assert maps_reviews_url(None, 39.0, -75.0) is None
    assert maps_reviews_url(fp, None, -75.0) is None
    assert maps_reviews_url(fp, 39.0, None) is None
    # a KG id is not a fingerprint and cannot build this URL
    assert maps_reviews_url("/g/11examplekg", 39.0, -75.0) is None


def test_place_coordinates_beat_the_viewport():
    """`@lat,lng` is where the map was pointing; `!3d!4d` is where the place is."""
    url = ("https://www.google.com/maps/place/Martin+Honda/@39.0710456,-76.3012658,9z/"
           "data=!4m6!3m5!1s0x89c7aa3edff67c63:0x3672dc0023b11b8f"
           "!8m2!3d39.6873533!4d-75.741334")
    parsed = parse_maps_url(url)
    assert parsed["latitude"] == 39.6873533
    assert parsed["longitude"] == -75.741334


def test_viewport_coordinates_used_when_no_place_coordinates():
    parsed = parse_maps_url("https://www.google.com/maps/place/Foo/@39.07,-76.30,9z/")
    assert parsed["latitude"] == 39.07
    assert parsed["longitude"] == -76.30


# Google's own documented example place id, plus the Googleplex.
PLACE_ID_CASES = [
    ("ChIJN1t_tDeuEmsRUsoyG83frY4", "0x6b12ae37b47f5b37:0x8eaddfcd1b32ca52", 10281119596374313554),
    ("ChIJj61dQgK6j4AR4GeTYWZsKWw", "0x808fba02425dad8f:0x6c296c66619367e0", 7793879817120868320),
]


def test_place_id_decodes_to_fingerprint_and_cid():
    """A ChIJ… id is the fingerprint in protobuf — decodable with no API call."""
    for place_id, fingerprint, cid in PLACE_ID_CASES:
        assert fingerprint_from_place_id(place_id) == fingerprint
        assert cid_from_fingerprint(fingerprint) == cid


def test_place_id_round_trips():
    for place_id, fingerprint, _ in PLACE_ID_CASES:
        assert place_id_from_fingerprint(fingerprint) == place_id


def test_place_id_rejects_what_it_cannot_decode():
    assert fingerprint_from_place_id("") is None
    assert fingerprint_from_place_id("not-a-place-id") is None
    assert fingerprint_from_place_id("/g/11examplekg") is None
    # right prefix, wrong length
    assert fingerprint_from_place_id("ChIJshort") is None
    # a longer (non-27-char) id is not guessed at
    assert fingerprint_from_place_id("ChIJ" + "A" * 40) is None


def test_place_id_is_classified_as_place_id():
    assert classify_input("ChIJN1t_tDeuEmsRUsoyG83frY4") == "place_id"
    assert classify_input("GhIJQWDl0CIeQUARxks3icF8U8A") == "place_id"
    # unchanged behaviour for the other forms
    assert classify_input("0xab:0xcd") == "place_id"
    assert classify_input("acme coffee") == "name"
