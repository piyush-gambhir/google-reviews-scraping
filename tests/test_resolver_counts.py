from grscraper.resolver import (
    _extract_review_count_from_aria,
    _extract_review_count_from_block,
)


def test_count_from_aria_label():
    """The aria-label survives panels where the '(1,086)' text does not render."""
    assert _extract_review_count_from_aria("1,086 reviews") == 1086
    assert _extract_review_count_from_aria("1 review") == 1
    assert _extract_review_count_from_aria("4.3 stars ") is None
    assert _extract_review_count_from_aria(None) is None
    assert _extract_review_count_from_aria("") is None


def test_count_from_block_text_still_works():
    assert _extract_review_count_from_block("4.9(102)") == 102
    assert _extract_review_count_from_block("4.9 (1,234)") == 1234
    assert _extract_review_count_from_block("4.3") is None
    assert _extract_review_count_from_block(None) is None
