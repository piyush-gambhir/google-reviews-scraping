import re

from bs4 import BeautifulSoup, Tag

from . import config
from . import selectors as sel
from .db import utcnow
from .models import Review

_RATING_RE = re.compile(r"(\d+(?:\.\d+)?)")
_STATS_REVIEWS_RE = re.compile(r"([\d,]+)\s*reviews?", re.IGNORECASE)
_STATS_PHOTOS_RE = re.compile(r"([\d,]+)\s*photos?", re.IGNORECASE)
_PHOTO_URL_RE = re.compile(r'url\("?([^")]+)"?\)')


def _txt(node: Tag | None) -> str | None:
    if node is None:
        return None
    t = node.get_text(strip=True)
    return t or None


def _attr(node: Tag | None, name: str) -> str | None:
    if node is None:
        return None
    v = node.get(name)
    return v if v else None


def parse_review_card(html: str | Tag, business_id: int) -> Review | None:
    """Parse one review card HTML/element into a Review.

    Returns None if the element is not a valid review card.
    """
    if isinstance(html, str):
        soup = BeautifulSoup(html, "html.parser")
        card = soup.select_one(sel.REVIEW_CARD)
    else:
        card = html
    if card is None:
        return None
    review_id = card.get(sel.REVIEW_CARD_FIELDS["review_id_attr"])
    if not review_id:
        return None

    fields = sel.REVIEW_CARD_FIELDS

    name = _txt(card.select_one(fields["reviewer_name"]))
    reviewer_link_node = card.select_one(fields["reviewer_link"])
    reviewer_url = _attr(reviewer_link_node, fields["reviewer_link_attr"])
    photo_node = card.select_one(fields["reviewer_photo"])
    reviewer_photo = _attr(photo_node, "src")

    stats_text = _txt(card.select_one(fields["reviewer_stats"]))
    reviewer_reviews = None
    reviewer_photos = None
    if stats_text:
        m = _STATS_REVIEWS_RE.search(stats_text)
        if m:
            reviewer_reviews = int(m.group(1).replace(",", ""))
        m = _STATS_PHOTOS_RE.search(stats_text)
        if m:
            reviewer_photos = int(m.group(1).replace(",", ""))

    rating_node = card.select_one(fields["rating"])
    rating_aria = _attr(rating_node, fields["rating_attr"])
    rating = None
    if rating_aria:
        m = _RATING_RE.search(rating_aria)
        if m:
            rating = int(float(m.group(1)))

    relative_date = _txt(card.select_one(fields["relative_date"]))

    review_text_nodes = card.select(fields["review_text"])
    review_text = _txt(review_text_nodes[0]) if review_text_nodes else None

    photo_urls: list[str] = []
    for btn in card.select(fields["review_photo_buttons"]):
        style = btn.get("style") or ""
        m = _PHOTO_URL_RE.search(style)
        if m:
            photo_urls.append(m.group(1))

    owner_reply = None
    owner_reply_date = None
    reply_block = card.select_one(fields["owner_reply_block"])
    if reply_block is not None:
        reply_text_node = reply_block.select_one(fields["owner_reply_text"])
        owner_reply = _txt(reply_text_node) or _txt(reply_block)
        owner_reply_date = _txt(reply_block.select_one(fields["owner_reply_date"]))

    return Review(
        review_id=review_id,
        business_id=business_id,
        reviewer_name=name,
        reviewer_url=reviewer_url,
        reviewer_photo=reviewer_photo,
        reviewer_reviews=reviewer_reviews,
        reviewer_photos=reviewer_photos,
        rating=rating,
        relative_date=relative_date,
        review_text=review_text,
        photo_urls=photo_urls,
        owner_reply=owner_reply,
        owner_reply_date=owner_reply_date,
        scraped_at=utcnow(),
        scraper_version=config.SCRAPER_VERSION,
    )


def parse_review_cards(html: str, business_id: int) -> list[Review]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Review] = []
    for card in soup.select(sel.REVIEW_CARD):
        r = parse_review_card(card, business_id)
        if r:
            out.append(r)
    return out
