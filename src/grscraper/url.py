import re
from urllib.parse import quote

PLACE_FINGERPRINT_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
GOOGLE_KG_ID_RE = re.compile(r"!16s(?:%2F|/)g(?:%2F|/)([^!?/&]+)")
LATLNG_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
PLACE_FINGERPRINT_PLAIN_RE = re.compile(r"^0x[0-9a-fA-F]+:0x[0-9a-fA-F]+$")
KG_ID_PLAIN_RE = re.compile(r"^/g/[A-Za-z0-9_]+$")


def parse_maps_url(url: str) -> dict:
    """Extract canonical identifiers from any Maps URL we encounter."""
    out = {
        "place_fingerprint": None,
        "google_kg_id": None,
        "latitude": None,
        "longitude": None,
    }
    if not url:
        return out
    m = PLACE_FINGERPRINT_RE.search(url)
    if m:
        out["place_fingerprint"] = m.group(1)
    m = GOOGLE_KG_ID_RE.search(url)
    if m:
        out["google_kg_id"] = f"/g/{m.group(1)}"
    m = LATLNG_RE.search(url)
    if m:
        out["latitude"] = float(m.group(1))
        out["longitude"] = float(m.group(2))
    return out


def classify_input(value: str) -> str:
    v = value.strip()
    if not v:
        raise ValueError("empty input")
    if v.startswith("http://") or v.startswith("https://"):
        if "google." in v and "/maps" in v:
            return "maps_url"
    if PLACE_FINGERPRINT_PLAIN_RE.match(v):
        return "place_id"
    if KG_ID_PLAIN_RE.match(v):
        return "place_id"
    return "name"


def maps_search_url(query: str) -> str:
    return f"https://www.google.com/maps/search/{quote(query)}"


def maps_place_by_id_url(place_id: str) -> str:
    """Build a Maps URL that resolves a place by its ID/fingerprint."""
    if PLACE_FINGERPRINT_PLAIN_RE.match(place_id):
        return f"https://www.google.com/maps/search/?api=1&query=Google&query_place_id={place_id}"
    if place_id.startswith("/g/"):
        return f"https://www.google.com/maps/search/?api=1&query={quote(place_id)}"
    return f"https://www.google.com/maps/search/?api=1&query_place_id={quote(place_id)}"
