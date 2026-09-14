# grscraper — Google Maps reviews scraper

A resumable scraper that collects retrievable Google Maps reviews, stores them in SQLite, and exports to CSV/JSON/NDJSON. Google can withhold reviews or change its DOM; a successful run does not guarantee a complete collection.

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
mkdir -p inputs
printf "value\nacme coffee roasters\n" > inputs/test.csv
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
ChIJN1t_tDeuEmsRUsoyG83frY4
```

A `ChIJ…` Places API place id is accepted directly — it is decoded offline into the
`0x…:0x…` fingerprint Maps actually speaks, with no API call and no key. Note Google
documents that place ids **can change** and are **not guaranteed unique**, and recommends
refreshing them yearly, so the fingerprint is the stabler key to store.

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

Exit codes: `0` clean · `1` error · `2` CAPTCHA or blocked work remains ·
`3` scrape fine but a sink failed · `4` scrape failures or exhausted retries.
Blocked work requires operator review before retrying.

## Tuning (env vars)

- `GRS_THROTTLE_BUSINESS_MIN_MS` / `GRS_THROTTLE_BUSINESS_MAX_MS` — wait between businesses (default 5000–15000)
- `GRS_THROTTLE_SCROLL_MIN_MS` / `GRS_THROTTLE_SCROLL_MAX_MS` — wait between scrolls (default 1500–2500)
- `GRS_MAX_RETRIES` — per-business retry budget across runs (default 3)
- `GRS_PANE_ATTEMPTS` — in-run attempts per business, each on a fresh browser context (default 3). Whether Maps serves the full place panel or a cut-down one with no Reviews tab is decided when the context is created and never changes inside it, so re-rolling the context is the only retry that helps. These attempts do not consume `GRS_MAX_RETRIES`.
- `GRS_BUSINESS_TIMEOUT_S` — cooperative scroll-loading deadline (default 600); navigation and individual browser operations have separate timeouts
- `GRS_USER_AGENT` — override Chrome UA string
- `GRS_BROWSER_CHANNEL` (default `chromium`) — Playwright ≥1.49 resolves `headless=True` to a separate `chromium_headless_shell` binary, which is easier to fingerprint; `chromium` selects the full browser in new-headless mode
- `GRS_HEADED` — run headed (needs an X server in a container; the image wraps the entrypoint in `xvfb-run`). Measured against a live listing, this made **no** difference to whether reviews were withheld — 3/5 headed vs 3/5 headless
- `GRS_STEALTH` (default on) — client-hint headers plus JS patches for the automation signals headless fails

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

## What you actually get

Google serves a **limited view** panel to clients it doesn't like: the place renders with
rating, address and hours, but the Reviews tab and every review card are missing. Google's
own copy attributes it to "unusual traffic" on your network. Measured against a live listing:

- Roughly **40% of fresh browser contexts** draw it.
- The draw is made when the **context** is created and never re-rolls inside it — reloads and
  new pages stay degraded. Only a new context draws again, which is what `GRS_PANE_ATTEMPTS` does.
- Per-session yield **decays with request volume** (45 → 10 → 5 reviews preloaded as a session
  went on). For free-tier scraping, pacing is worth more than fingerprint tweaking.

So a run is partial by nature, and `run` reports how partial: every business gets a `coverage`
entry with `collected`, `advertised` (what Google advertises) and their `ratio`. A business that
resolves but yields zero cards is recorded as **failed**, never as a successful empty scrape.

There is no way around this for a listing you don't own. The Places API returns at most
**5 reviews** and does not paginate; the Business Profile API returns all of them but only for
locations you have verified ownership of.

## Output

`sync` emits one versioned JSON document, pinned by
[`schemas/scrape-result.v1.json`](schemas/scrape-result.v1.json) and documented
in [docs/SCHEMA.md](docs/SCHEMA.md). Two things consumers get wrong: Google's
Maps surface has **no absolute review dates** (only `"2 months ago"`), and
`review_count` is what Google advertises, which is not the same as how many
reviews you actually got.

## Scope

- ✅ Resumable across crashes (interrupted businesses restart under an exclusive process lock)
- ✅ Idempotent re-runs (deduped by `data-review-id`)
- ✅ Mixed input types
- ✅ Deployable as a container — job, HTTP service, or Lambda
- ❌ Proxy rotation, distributed workers, mid-business resume — out of v1, add when you outgrow free
- ❌ Incremental fetch — requested completed businesses are refreshed by `sync`; `--no-refresh` keeps the old queue-only behavior. Existing review IDs are retained without updating edited text.
- ❌ Absolute review timestamps — Google doesn't expose them here. If you own the listing, the Business Profile API does.

## Tests

```
.venv/bin/pytest        # offline tests
.venv/bin/ruff check    # lint
```

Live integration relies on Google's actual Maps DOM. When Google rotates classes, fix selectors in [src/grscraper/selectors.py](src/grscraper/selectors.py) — that's the single chokepoint.

## API and repository guide

**Yes, the repository exposes an HTTP API when started with `grscraper serve`.**
`POST /scrape` runs synchronously. `GET /`, `/healthz`, and `/readyz` are probe
aliases. The Docker image defaults to `sync`, so running the image alone does
not start an HTTP server. A Lambda handler is also provided; it is not an HTTP
API Gateway adapter.

- [API contract and examples](docs/API.md)
- [Machine-readable OpenAPI 3.1 specification](schemas/openapi.json)
- [Module structure and engineering roadmap](docs/ARCHITECTURE.md)
- [Deployment and state storage](docs/DEPLOY.md)

### Reliability update: behavior changes

- HTTP startup requires `GRS_SERVER_TOKEN`. For development or an authenticated
  ingress, explicitly opt out with `GRS_ALLOW_UNAUTHENTICATED=1`.
- HTTP callers can only select sink URIs already listed in `GRS_SINKS`.
- `sync` refreshes explicitly requested completed targets (including configured
  `GRS_TARGETS`). Use `--no-refresh` to skip them. With no targets, it drains
  existing eligible queue entries without refreshing completed ones.
- Failed work keeps its retry budget. Blocked work stays blocked until
  `retry --status blocked` or an explicit `sync --retry-blocked`. The old
  `--no-retry-blocked` flag is accepted but no longer needed.
- CLI, HTTP, and Lambda scrapes coordinate through database and profile locks
  on Linux/macOS local filesystems. Deploy one writer per state volume;
  object-storage mounts and distributed shared state are unsupported.

Completed targets refresh after the requested batch has no eligible unfinished
entries. This lets repeated `limit`-bounded calls finish later targets before
starting another refresh cycle.
