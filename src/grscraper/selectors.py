"""All Google Maps DOM selectors live here.

Google rotates class names occasionally. When the scraper breaks, fix here.
"""

REVIEWS_TAB = 'button[role="tab"][aria-label*="Reviews"]'

REVIEWS_SCROLL_CONTAINER = "div.m6QErb.DxyBCb.kA9KIf.dS8AEf.XiKgde"

REVIEW_CARD = "div.jftiEf[data-review-id]"

REVIEW_CARD_FIELDS = {
    "review_id_attr": "data-review-id",
    "reviewer_name": ".d4r55",
    "reviewer_link": 'button[data-href*="/contrib/"]',
    "reviewer_link_attr": "data-href",
    "reviewer_stats": ".RfnDt",
    "reviewer_photo": "img.NBa7we",
    "rating": ".kvMYJc",
    "rating_attr": "aria-label",
    "relative_date": ".rsqaWe",
    "review_text": ".wiI7pd",
    "see_more_btn": ".w8nwRe",
    "review_photo_buttons": "button[data-photo-index]",
    "review_photo_attr": "style",
    "owner_reply_block": ".CDe7pd",
    "owner_reply_text": ".wiI7pd",
    "owner_reply_date": ".DZSIDd",
}

PLACE_TITLE = "h1.DUwDvf"
PLACE_RATING_AND_COUNT_BLOCK = "div.F7nice"
PLACE_RATING = "div.F7nice span[aria-hidden]"
# The count also rides an aria-label ("1,086 reviews") on a sibling span. That
# label survives in panels where the "(1,086)" text does not render, so it is
# the more reliable of the two sources.
PLACE_REVIEW_COUNT_ARIA = 'div.F7nice span[role="img"][aria-label*="review"]'
PLACE_CATEGORY = "button.DkEaL"
PLACE_ADDRESS = 'button[data-item-id="address"]'
PLACE_ADDRESS_TEXT = "div.Io6YTe"
PLACE_PHONE = 'button[data-item-id^="phone:"]'
PLACE_WEBSITE = 'a[data-item-id="authority"]'
PLACE_PLUS_CODE = 'button[data-item-id="oloc"]'
PLACE_HOURS_BTN = 'button[data-item-id="oh"]'
PLACE_HOURS_TABLE = "table.eK4R0e tr"

CAPTCHA_URL_FRAGMENT = "/sorry/index"

# Google's "limited view" panel, shipped Feb 2026. It renders the place with
# rating, address and hours but strips reviews, photos and popular times, and
# carries only Overview/About tabs. Google's own copy says it appears when
# "unusual traffic" is seen on your network. Matching the phrase is what lets us
# report a withheld pane as exactly that, instead of as "this place has no
# reviews" — the two are indistinguishable from the DOM alone.
LIMITED_VIEW_TEXT = "limited view"
