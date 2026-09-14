import base64
import re
import struct
from urllib.parse import quote

PLACE_FINGERPRINT_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
GOOGLE_KG_ID_RE = re.compile(r"!16s(?:%2F|/)g(?:%2F|/)([^!?/&]+)")
LATLNG_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
# `@lat,lng` is the map viewport, which is not the place: a URL shared from a
# zoomed-out search can sit a hundred kilometres away. `!3d!4d` inside the data
# payload is the listing's own position, so prefer it when present.
PLACE_LATLNG_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
PLACE_FINGERPRINT_PLAIN_RE = re.compile(r"^0x[0-9a-fA-F]+:0x[0-9a-fA-F]+$")
KG_ID_PLAIN_RE = re.compile(r"^/g/[A-Za-z0-9_]+$")
# Places API place ids: 27 base64url chars. The ChIJ/GhIJ prefix is not a magic
# string, it is the protobuf framing itself (bytes 0a 12 09) showing through the
# encoding, which is why only these decode to a fingerprint.
GOOGLE_PLACE_ID_RE = re.compile(r"^(?:ChIJ|GhIJ)[A-Za-z0-9_-]{23}$")


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
    m = PLACE_LATLNG_RE.search(url) or LATLNG_RE.search(url)
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
    if GOOGLE_PLACE_ID_RE.match(v):
        return "place_id"
    return "name"


def fingerprint_from_place_id(place_id: str) -> str | None:
    """Decode a `ChIJ…` Places API id into the `0x…:0x…` Maps fingerprint.

    A place id is base64url-encoded protobuf holding the two 64-bit halves of
    the fingerprint: `{1: {1: fixed64 high, 2: fixed64 low}}`. Decoding is pure
    arithmetic — no API call, no key, no quota — which matters because every
    internal Maps surface speaks the hex form and none of them accept `ChIJ…`.

    Returns None for anything that is not exactly that 20-byte shape, rather
    than guessing at a longer id we have not seen.
    """
    if not place_id or not GOOGLE_PLACE_ID_RE.match(place_id):
        return None
    try:
        raw = base64.urlsafe_b64decode(place_id + "=" * (-len(place_id) % 4))
    except (ValueError, TypeError):
        return None
    if len(raw) != 20 or raw[0] != 0x0A or raw[1] != 0x12 or raw[2] != 0x09 or raw[11] != 0x11:
        return None
    high = struct.unpack("<Q", raw[3:11])[0]
    low = struct.unpack("<Q", raw[12:20])[0]
    return f"0x{high:x}:0x{low:x}"


def place_id_from_fingerprint(fingerprint: str) -> str | None:
    """Inverse of `fingerprint_from_place_id`. Mostly useful for round-trip tests.

    Note this cannot be done from a CID alone: a CID is only the low half, and
    the high half is not recoverable from it.
    """
    if not fingerprint or not PLACE_FINGERPRINT_PLAIN_RE.match(fingerprint):
        return None
    high, low = (int(part, 16) for part in fingerprint.split(":"))
    raw = b"\x0a\x12\x09" + struct.pack("<Q", high) + b"\x11" + struct.pack("<Q", low)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


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


def maps_reviews_url(
    place_fingerprint: str | None,
    latitude: float | None,
    longitude: float | None,
    hl: str = "en",
) -> str | None:
    """Deep link that opens a place's reviews list directly.

    `!9m1!1b1` is Maps' "show the reviews list" flag. Navigating here instead of
    to the place page is not an optimisation. A place URL copied out of Maps
    *search results* carries the originating query in its data payload, and that
    variant renders a panel with no Reviews tab at all — the tab-click path has
    nothing to click, and the run reports a resolved place with zero reviews.

    The `@lat,lng,17z` path segment is required: `/maps/place//data=!4m7…`
    on its own renders no place. Returns None when the caller lacks the
    identifiers to build it, so callers fall back to the tab-click path.
    """
    if not place_fingerprint or latitude is None or longitude is None:
        return None
    if not PLACE_FINGERPRINT_PLAIN_RE.match(place_fingerprint):
        return None
    return (
        f"https://www.google.com/maps/place//@{latitude},{longitude},17z/"
        f"data=!4m7!3m6!1s{place_fingerprint}"
        f"!8m2!3d{latitude}!4d{longitude}!9m1!1b1?hl={hl}"
    )


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
