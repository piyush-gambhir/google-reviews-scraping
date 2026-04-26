from pathlib import Path

from grscraper.parser import parse_review_cards

FIXTURE = Path(__file__).parent / "fixtures" / "sample_cards.html"


def test_parse_fixture_yields_three_reviews():
    html = FIXTURE.read_text(encoding="utf-8")
    reviews = parse_review_cards(html, business_id=1)
    assert len(reviews) == 3
    for r in reviews:
        assert r.review_id, "review_id is required"
        assert r.business_id == 1
        assert r.reviewer_name, "reviewer_name should be present"
        assert r.rating is not None and 1 <= r.rating <= 5
        assert r.relative_date, "relative_date should be present"
        assert r.review_text, "review_text should be present"
        assert r.scraper_version
        assert r.scraped_at


def test_parse_first_review_specific_fields():
    html = FIXTURE.read_text(encoding="utf-8")
    reviews = parse_review_cards(html, business_id=42)
    first = reviews[0]
    # confirmed live: first reviewer is Alka Joshi, 5 stars, 5 months ago
    assert first.reviewer_name == "Alka Joshi"
    assert first.rating == 5
    assert first.reviewer_url and "/contrib/" in first.reviewer_url
    assert first.reviewer_photo and first.reviewer_photo.startswith("https://")
    assert first.reviewer_reviews == 8
    assert first.reviewer_photos == 2
    assert "5 months ago" in (first.relative_date or "")


def test_parse_empty_html_returns_nothing():
    assert parse_review_cards("<div></div>", business_id=1) == []
