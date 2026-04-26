from dataclasses import dataclass, field


@dataclass
class Business:
    input_value: str
    input_type: str
    place_fingerprint: str | None = None
    google_kg_id: str | None = None
    canonical_url: str | None = None
    name: str | None = None
    address: str | None = None
    category: str | None = None
    phone: str | None = None
    website: str | None = None
    hours_json: str | None = None
    plus_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    overall_rating: float | None = None
    review_count: int | None = None
    status: str = "queued"
    status_reason: str | None = None
    retry_count: int = 0
    id: int | None = None


@dataclass
class Review:
    review_id: str
    business_id: int
    reviewer_name: str | None = None
    reviewer_url: str | None = None
    reviewer_photo: str | None = None
    reviewer_reviews: int | None = None
    reviewer_photos: int | None = None
    rating: int | None = None
    relative_date: str | None = None
    review_text: str | None = None
    review_lang: str | None = None
    photo_urls: list[str] = field(default_factory=list)
    owner_reply: str | None = None
    owner_reply_date: str | None = None
    scraped_at: str | None = None
    scraper_version: str | None = None
