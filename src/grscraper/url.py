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


def cid_from_fingerprint(fingerprint: str) -> int | None:
    """Return the decimal CID encoded in the second half of `0x…:0x…`.

    Google's hex place fingerprint is two values; the second is the CID, which
    `maps?cid=` accepts directly.
    """
    if not PLACE_FINGERPRINT_PLAIN_RE.match(fingerprint or ""):
        return None
    try:
        return int(fingerprint.split(":")[1], 16)
    except (IndexError, ValueError):
        return None


def maps_place_by_id_url(place_id: str) -> str:
    """Build a Maps URL that resolves a place by its ID/fingerprint.

    Only the `cid` form actually lands on a place page. Verified against a live
    listing: `?cid=<decimal>` resolves, while `?q=place_id:0x…:0x…` and
    `query_place_id=0x…` are treated as literal search text and return a
    results page — `query_place_id` wants a `ChIJ…` Places id, not the hex form.
    """
    cid = cid_from_fingerprint(place_id)
    if cid is not None:
        return f"https://www.google.com/maps?cid={cid}"
    # Knowledge Graph ids have no reliable direct URL, so fall back to search
    # and let the result picker do the work. Best effort.
    return maps_search_url(place_id)
