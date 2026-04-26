from grscraper.url import classify_input, maps_search_url, parse_maps_url

CANONICAL_URL = (
    "https://www.google.com/maps/place/Lagya+Visa+(A+unit+of+PGN+Travel+Shop)/"
    "@28.6382303,77.1205162,17z/data=!4m8!3m7!1s0x390d03bb72e52773:0xf99337532b7b904c"
    "!8m2!3d28.6382303!4d77.1205162!9m1!1b1!16s%2Fg%2F11ltlbsy8b?entry=ttu"
)


def test_parse_canonical_url():
    parsed = parse_maps_url(CANONICAL_URL)
    assert parsed["place_fingerprint"] == "0x390d03bb72e52773:0xf99337532b7b904c"
    assert parsed["google_kg_id"] == "/g/11ltlbsy8b"
    assert parsed["latitude"] == 28.6382303
    assert parsed["longitude"] == 77.1205162


def test_parse_empty_url():
    assert parse_maps_url("")["place_fingerprint"] is None
    assert parse_maps_url("https://example.com")["place_fingerprint"] is None


def test_classify_input():
    assert classify_input("pgn travel shop") == "name"
    assert classify_input("https://www.google.com/maps/place/foo") == "maps_url"
    assert classify_input("0x390d03bb72e52773:0xf99337532b7b904c") == "place_id"
    assert classify_input("/g/11ltlbsy8b") == "place_id"
    assert classify_input("https://example.com/maps/foo") == "name"


def test_maps_search_url_encoding():
    assert "pgn%20travel%20shop" in maps_search_url("pgn travel shop")
