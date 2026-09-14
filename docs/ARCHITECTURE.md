# Architecture and improvement roadmap

## Current structure

Keep the existing `src` package: it already separates the browser, storage,
parsing, and delivery responsibilities. The new request and locking modules
provide shared behavior without moving existing import paths.

```text
google-reviews-scraping/
├── src/grscraper/
│   ├── cli.py             # command-line adapter
│   ├── server.py          # HTTP adapter
│   ├── awslambda.py       # Lambda event adapter
│   ├── request.py         # shared request validation and response shaping
│   ├── sync.py            # ingest → refresh → run → snapshot → deliver
│   ├── runner.py          # serial business processing and status transitions
│   ├── locking.py         # process ownership of database and browser profile
│   ├── browser.py         # Chromium lifecycle
│   ├── resolver.py        # input navigation and place metadata
│   ├── reviews.py         # review tab, scrolling, expansion
│   ├── parser.py          # HTML → review records
│   ├── selectors.py       # DOM selectors
│   ├── stealth.py         # optional browser compatibility patches
│   ├── db.py              # SQLite schema and repository operations
│   ├── models.py          # business and review dataclasses
│   ├── targets.py         # inline input parsing/ingestion
│   ├── ingest.py          # file ingestion
│   ├── url.py             # identifiers and Maps URLs
│   ├── snapshot.py        # canonical nested JSON document
│   ├── export.py          # tabular and NDJSON exports
│   ├── sinks.py           # stdout/file/HTTP/S3/GCS delivery
│   └── config.py          # environment configuration
├── schemas/               # output JSON Schema and OpenAPI contract
├── tests/                 # offline fixtures and regression tests
├── docs/                  # API, architecture, deployment, output contract
├── .github/workflows/     # tests and container build/publishing
├── Dockerfile             # standard container, default: sync
├── Dockerfile.lambda      # Lambda runtime adapter
└── pyproject.toml         # dependencies, CLI registration, lint/test settings
```

## State and execution

`sync()` and `run()` acquire advisory locks for both database and profile.
Nested calls in one thread reuse ownership. Competing processes fail quickly;
process exit releases the locks. Only after ownership is acquired may a runner
recover `resolving`/`scraping` rows left by an interrupted run. Recovery consumes
one retry and records the interruption. Linux and macOS local filesystems are
the supported deployment targets; these are not distributed leases.

Each business gets a new page and resolves again, including previously
`resolved` entries. Ordinary business failures are persisted and processing
continues after throttling. CAPTCHA halts the run and requires explicit
operator recovery. Requested `done` rows refresh on sync; `failed` rows retain
their retry count, and exhausted/blocked rows remain visible as nonzero outcomes.

## Next improvements, in priority order

| Priority | Work | Acceptance criteria |
|---|---|---|
| P1 | Persist partial review batches and completeness metadata | Interrupted scrolling preserves collected reviews; consumers see stop reason, expected vs collected count, and last successful collection time |
| P1 | True total business deadline | Resolution, scrolling, parsing and browser teardown share a cancellable budget; a stuck browser cannot hold the worker indefinitely |
| P1 | Durable asynchronous API | `POST /v1/jobs` returns 202/job ID; status/results/cancel endpoints survive restart; repeated idempotency keys reuse a job |
| P1 | Delivery outbox | Persist payload plus per-sink status before delivery; replay failed deliveries without scraping; webhook consumers dedupe by delivery ID |
| P1 | Browser fixtures for changing DOM | Cover slow loads, virtualized cards, no-review listings, ambiguous search results, consent pages and partial loads |
| P2 | Update edited reviews | Preserve first-seen time, record last-seen time, update text/rating/owner replies for an existing review ID |
| P2 | Input aliases and schema migrations | Name/URL variants resolve to one business without fingerprint conflicts; migrations have upgrade tests |
| P2 | Reproducible builds | Lock all runtime dependencies and align Playwright package/browser versions; build and smoke-test both image variants |
| P2 | Operational visibility | Structured run/job IDs, per-stage durations, queue depth, retry counts and sink delivery metrics; readiness checks real dependencies |
| P2 | Paginated, scoped results | Query results by job/business with stable cursors instead of loading the whole SQLite store into memory |

A future larger service can group adapters into `api/`, browser code into
`scraping/`, storage into `storage/`, and delivery into `delivery/`. Move modules
when those components gain independent contracts; a folder-only rewrite would
not address the reliability issues above.

## Limits that remain

- `done` means the collector returned nonempty parsed cards, not proof that every
  advertised review was retrieved. Genuine zero-review places remain failures.
- The scrolling deadline is cooperative and does not cover the entire business.
- Retries are budgeted across runs, but no persistent exponential backoff or
  scheduled `next_attempt_at` exists yet.
- Review storage deduplicates IDs; it does not update edited reviews yet.
- Authentication is one shared operator token. No tenants, roles or per-job
  result isolation exist. HTTP request targets can drain the shared queue.
- DOM scraping, cloud SDK delivery, Docker runtime behavior and public ingress
  still need environment-specific live validation; offline tests cannot prove them.

Completed targets refresh after the requested batch has no eligible unfinished
entries. This lets repeated `limit`-bounded calls finish later targets before
starting another refresh cycle.
