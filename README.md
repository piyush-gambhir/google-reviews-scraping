# grscraper — Google Maps reviews scraper

A free, resumable scraper that pulls every review for businesses you point it at, stores them in SQLite, and exports to CSV/JSON/NDJSON.

Targets the Google **Maps** surface (not Search) which is far more permissive about automated access. Inputs can be plain business names, Maps URLs, or place IDs — mixed in any order.

Runs as a CLI on your machine, or as a container on Cloud Run, Lambda, Kubernetes, or anything else that runs images.

## Run it in Docker

```bash
docker run --rm -v grscraper-data:/data \
  -e GRS_TARGETS="acme coffee roasters" \
  ghcr.io/piyush-gambhir/grscraper:latest sync
```

That enqueues the target, scrapes it, and writes a single JSON document to
stdout. Point `GRS_SINKS` at a file, webhook, S3 or GCS to send it elsewhere.
Mount `/data` to keep the queue and browser profile between runs.

See [docs/DEPLOY.md](docs/DEPLOY.md) for Cloud Run jobs, services, Lambda and
Kubernetes, and [docs/SCHEMA.md](docs/SCHEMA.md) for the output contract.

## Quickstart (local)

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium

.venv/bin/grscraper init
echo -e "value\nacme coffee roasters" > inputs/test.csv
.venv/bin/grscraper ingest inputs/test.csv
.venv/bin/grscraper -v run
.venv/bin/grscraper export reviews --format csv
```

The last command writes `data/exports/reviews_<UTC-timestamp>.csv`.

## Input formats

`inputs/*.csv` — one of:

```
value
acme coffee roasters
https://www.google.com/maps/place/Some+Place/.../data=...
0x1234567890abcdef:0xfedcba0987654321
/g/11examplekg
```

Or with explicit type column:

```
value,type
acme coffee roasters,name
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

grscraper sync [target ...] [--sink URI] [--limit N]  # one-shot, for schedulers
grscraper serve [--port N]                            # HTTP mode
```

`sync` collapses init/ingest/run/export into one idempotent command and hands
the result to every configured sink. It is what the container runs by default.

```bash
grscraper sync "acme coffee roasters" --sink ./reviews.json --sink https://example.com/ingest
```

Exit codes: `0` clean · `1` error · `2` CAPTCHA (halted early — back off, don't
retry) · `3` scrape fine but a sink failed.

## Tuning (env vars)

- `GRS_THROTTLE_BUSINESS_MIN_MS` / `GRS_THROTTLE_BUSINESS_MAX_MS` — wait between businesses (default 5000–15000)
- `GRS_THROTTLE_SCROLL_MIN_MS` / `GRS_THROTTLE_SCROLL_MAX_MS` — wait between scrolls (default 1500–2500)
- `GRS_MAX_RETRIES` — per-business retry budget (default 3)
- `GRS_BUSINESS_TIMEOUT_S` — hard timeout per business (default 600)
- `GRS_USER_AGENT` — override Chrome UA string

For deployment: `GRS_TARGETS`, `GRS_SINKS`, `GRS_SINK_HTTP_TOKEN`,
`GRS_DATA_DIR`, `PORT`, `GRS_SERVER_TOKEN` — all in [docs/DEPLOY.md](docs/DEPLOY.md).

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

## Output

`sync` emits one versioned JSON document, pinned by
[`schemas/scrape-result.v1.json`](schemas/scrape-result.v1.json) and documented
in [docs/SCHEMA.md](docs/SCHEMA.md). Two things consumers get wrong: Google's
Maps surface has **no absolute review dates** (only `"2 months ago"`), and
`review_count` is what Google advertises, which is not the same as how many
reviews you actually got.

## Scope

- ✅ Resumable across crashes (status state lives in SQLite)
- ✅ Idempotent re-runs (deduped by `data-review-id`)
- ✅ Mixed input types
- ✅ Deployable as a container — job, HTTP service, or Lambda
- ❌ Proxy rotation, distributed workers, mid-business resume — out of v1, add when you outgrow free
- ❌ Incremental fetch (only new reviews since last run) — every run re-scrapes; dedup means it's a no-op if nothing changed
- ❌ Absolute review timestamps — Google doesn't expose them here. If you own the listing, the Business Profile API does.

## Tests

```
.venv/bin/pytest        # offline tests
.venv/bin/ruff check    # lint
```

Live integration relies on Google's actual Maps DOM. When Google rotates classes, fix selectors in [src/grscraper/selectors.py](src/grscraper/selectors.py) — that's the single chokepoint.
