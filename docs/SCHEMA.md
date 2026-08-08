# Output schema

Machine-readable: [`schemas/scrape-result.v1.json`](../schemas/scrape-result.v1.json)
(JSON Schema 2020-12). Every sink receives exactly this document.

```json
{
  "schema_version": "1.0",
  "scraper_version": "0.2.0",
  "generated_at": "2026-08-08T14:41:53+00:00",
  "run": {
    "total": 1, "done": 1, "failed": 0, "blocked": false, "reviews_added": 12
  },
  "businesses": [
    {
      "id": 1,
      "input_value": "acme coffee roasters",
      "input_type": "name",
      "place_fingerprint": "0x1234567890abcdef:0xfedcba0987654321",
      "google_kg_id": "/g/11examplekg",
      "canonical_url": "https://www.google.com/maps/place/...",
      "name": "Acme Coffee Roasters",
      "address": "...",
      "category": "Coffee shop",
      "phone": "+1 555-0100",
      "website": "https://...",
      "hours_json": "{\"Monday\": \"9 am–7 pm\"}",
      "plus_code": "QXR7+8M Example City",
      "latitude": 12.3,
      "longitude": 98.7,
      "overall_rating": 4.8,
      "review_count": 102,
      "created_at": "2026-08-08T14:00:00+00:00",
      "updated_at": "2026-08-08T14:05:00+00:00",
      "reviews": [
        {
          "review_id": "Ci9DQUlRQUNvZENodHljRjlvU0FNUExFRklYVFVSRUlE",
          "business_id": 1,
          "reviewer_name": "Jordan Rivera",
          "reviewer_url": "https://www.google.com/maps/contrib/100000000000000000000",
          "reviewer_photo": "https://example.test/avatar/1.jpg",
          "reviewer_reviews": 41,
          "reviewer_photos": 12,
          "rating": 5,
          "relative_date": "2 months ago",
          "review_text": "Friendly staff and a quick turnaround.",
          "review_lang": "en",
          "photo_urls": ["https://example.test/photo/1.jpg"],
          "owner_reply": "Thank you!",
          "owner_reply_date": "a month ago",
          "scraped_at": "2026-08-08T14:03:11+00:00",
          "scraper_version": "0.2.0"
        }
      ]
    }
  ]
}
```

## Versioning

`schema_version` tracks the envelope, `scraper_version` tracks the release.
Major bumps of `schema_version` are breaking; minor bumps only add optional
fields. Assert on the major and ignore fields you don't know.

## Things that will bite you if you assume otherwise

**There are no absolute review dates.** Google's Maps surface exposes only
relative ages — `"2 months ago"` — and so does this document. `owner_reply_date`
too. If you need a timestamp, derive it against `scraped_at` and treat it as
approximate, or use the Google Business Profile API for listings you own, which
does carry real ones.

**`review_count` ≠ `len(reviews)`.** The count is what Google advertises for the
business. The array is what was actually retrievable: Google withholds some
reviews, and a run that ends `blocked` truncates mid-scroll. Check
`run.blocked` before treating a short array as ground truth.

**`review_text` is often null.** Rating-only reviews are common. Filter before
doing anything textual.

**`reviews_added: 0` is not a failure.** Reviews dedupe on `review_id`, so a
re-run with no new reviews correctly adds nothing.

**`id` and `business_id` are store-local.** They are SQLite rowids — stable
within one `/data` volume, meaningless across deployments. For a durable key
use `place_fingerprint` (business) and `review_id` (review); both come from
Google and survive re-scrapes.

**`hours_json` is a JSON-encoded string**, not an object. Nested-parse it.

**`photo_urls` is always an array**, never null — iterate freely.

**Queue bookkeeping is omitted by default.** `status`, `status_reason` and
`retry_count` appear only with `--include-internal`.

## Relationship to `export combined`

Objects in `businesses` are identical to one line of
`grscraper export combined --format ndjson`. A consumer written against that
format needs one change: read `payload["businesses"]` instead of the bare list.

## Validating

```bash
pip install jsonschema
python -c "
import json, jsonschema, sys
schema = json.load(open('schemas/scrape-result.v1.json'))
jsonschema.validate(json.load(open(sys.argv[1])), schema)
print('valid')
" out.json
```

The test suite validates generated documents against this schema on every run,
so the file and the code cannot drift apart silently.
