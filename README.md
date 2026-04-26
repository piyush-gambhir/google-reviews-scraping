# grscraper — Google Maps reviews scraper

A free, resumable scraper that pulls every review for businesses you point it at, stores them in SQLite, and exports to CSV/JSON/NDJSON.

Targets the Google **Maps** surface (not Search) which is far more permissive about automated access. Inputs can be plain business names, Maps URLs, or place IDs — mixed in any order.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium

.venv/bin/grscraper init
echo -e "value\npgn travel shop" > inputs/test.csv
.venv/bin/grscraper ingest inputs/test.csv
.venv/bin/grscraper -v run
.venv/bin/grscraper export reviews --format csv
```

The last command writes `data/exports/reviews_<UTC-timestamp>.csv`.

## Input formats

`inputs/*.csv` — one of:

```
value
pgn travel shop
https://www.google.com/maps/place/Some+Place/.../data=...
0x390d03bb72e52773:0xf99337532b7b904c
/g/11ltlbsy8b
```

Or with explicit type column:

```
value,type
pgn travel shop,name
https://www.google.com/maps/place/Foo,maps_url
```

Plain newline-delimited files (no header) also work — types are auto-classified from the value.

## CLI

```
grscraper init                                       # create data/scraper.db
grscraper ingest <path>                              # parse & enqueue
grscraper status                                     # counts by status
grscraper run [--workers 1] [--limit N] [--no-headless] [--debug]
grscraper retry --status failed|blocked              # requeue prior failures
grscraper export reviews|businesses|combined --format csv|json|ndjson
```

## Tuning (env vars)

- `GRS_THROTTLE_BUSINESS_MIN_MS` / `GRS_THROTTLE_BUSINESS_MAX_MS` — wait between businesses (default 5000–15000)
- `GRS_THROTTLE_SCROLL_MIN_MS` / `GRS_THROTTLE_SCROLL_MAX_MS` — wait between scrolls (default 1500–2500)
- `GRS_MAX_RETRIES` — per-business retry budget (default 3)
- `GRS_BUSINESS_TIMEOUT_S` — hard timeout per business (default 600)
- `GRS_USER_AGENT` — override Chrome UA string

## When you hit a CAPTCHA

The scraper detects Google's `/sorry/` page and **stops the run immediately** — continuing while blocked makes things worse. The blocked business gets `status='blocked'`. To recover:

1. Wait at least an hour (longer is safer)
2. `grscraper run --debug` — runs headed so you can solve the CAPTCHA manually. Cookies persist in `data/browser_profile/` so the solve sticks
3. Once unblocked: `grscraper retry --status blocked` to requeue, then `grscraper run`

If you hit blocks repeatedly, raise the throttles:

```bash
GRS_THROTTLE_BUSINESS_MIN_MS=20000 GRS_THROTTLE_BUSINESS_MAX_MS=60000 \
  .venv/bin/grscraper run
```

## Scope

- ✅ Resumable across crashes (status state lives in SQLite)
- ✅ Idempotent re-runs (deduped by `data-review-id`)
- ✅ Mixed input types
- ❌ Proxy rotation, distributed workers, mid-business resume — out of v1, add when you outgrow free
- ❌ Incremental fetch (only new reviews since last run) — every run re-scrapes; dedup means it's a no-op if nothing changed

## Tests

```
.venv/bin/pytest        # offline tests
.venv/bin/ruff check    # lint
```

Live integration relies on Google's actual Maps DOM. When Google rotates classes, fix selectors in [src/grscraper/selectors.py](src/grscraper/selectors.py) — that's the single chokepoint.
