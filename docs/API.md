# HTTP API

Start with `GRS_SERVER_TOKEN=<secret> grscraper serve --port 8080`.
The server listens on `0.0.0.0`; TLS, request rate limits, connection limits,
and ingress policy belong to the reverse proxy/platform. This stdlib adapter
is a synchronous endpoint for a single trusted operator, not a multi-tenant API.

The presence of this code or Docker `EXPOSE 8080` does not establish that a
public deployment exists. No deployed service URL was verified in this review.

## Routes

| Method | Path | Authentication | Behavior |
|---|---|---|---|
| GET | `/`, `/healthz`, `/readyz` | None | `status`, versions, and in-process HTTP `busy` flag |
| POST | `/scrape` | Bearer token | Run sync and deliver results synchronously |

`/readyz` is currently a liveness alias: it does not check database access,
browser health, or whether another process holds a scrape lock. There are no
job polling, cancellation, review-listing, or pagination endpoints. Lambda
accepts the same direct request object; API Gateway events are not decoded.

## Request

```bash
curl --fail-with-body http://localhost:8080/scrape \
  -H "Authorization: Bearer $GRS_SERVER_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"targets":["acme coffee roasters"],"limit":1,"inline_result":true}'
```

| Field | Type / default | Meaning |
|---|---|---|
| `targets` | string, string array, or null | Null/omitted uses `GRS_TARGETS`; otherwise newline/semicolon-separated targets, optionally `value\|type` |
| `sinks` | string, string array, or null | Null/omitted uses `GRS_SINKS`; empty array disables delivery; HTTP overrides must exactly match preconfigured URIs |
| `limit` | integer 1–1000, or null | Maximum eligible businesses processed; null has no request-specific limit |
| `inline_result` | boolean, false | Include the versioned result document as `result` |
| `include_internal` | boolean, false | Include queue status/reason/retry fields in the document |
| `refresh` | boolean, true | Requeue requested businesses that are already done |

Unknown fields, wrong types, and invalid target declarations are rejected.
Bodies are limited to 1 MiB and require `Content-Type: application/json` when
nonempty. Chunked transfer encoding is unsupported. Body reads time out after
30 seconds of socket inactivity. Targets are limited to 1000 parsed entries,
8192 characters each. Navigated request URLs must use HTTPS on `google.com`,
`www.google.com`, or `maps.google.com`, with a `/maps` path and no credentials.
Regional domains and short URLs must first be expanded/normalized by the caller.
This initial-URL check is not a browser network sandbox; enforce egress policy
at the platform if untrusted clients can submit requests.

`GRS_ALLOW_UNAUTHENTICATED=1` is an explicit opt-out for a trusted ingress or
local development. When a server token is set, the token is always required.
HTTP clients cannot reset CAPTCHA blocks or retry budgets; those are operator
CLI actions. Lambda sink destinations rely on the function's IAM invocation
boundary and are not restricted to `GRS_SINKS`.

## Response

Successful empty-queue example (with delivery disabled):

```json
{
  "targets": 0,
  "ingested": {"inserted": 0, "skipped": 0},
  "requeued": 0,
  "run": {"total": 0, "done": 0, "failed": 0, "blocked": false, "reviews_added": 0},
  "delivery": {"delivered": [], "errors": []},
  "businesses": 0,
  "reviews": 0,
  "exit_code": 0,
  "blocked_remaining": 0,
  "retries_exhausted": 0
}
```

With `inline_result: true`, `result` contains the document described in
[SCHEMA.md](SCHEMA.md). The response and sinks include a snapshot of **the
whole database**, including prior targets; `limit` limits processing, not
output. This also means blocked/exhausted work elsewhere in that database can
make the response nonzero. Use separate state for separate operators.

| Status | Meaning |
|---|---|
| 200 | Sync completed with exit code 0, or probe succeeded |
| 400 | Malformed JSON, framing, or request fields |
| 401 | Missing/incorrect token, or auth configuration is absent |
| 404 | Unknown route |
| 408 | Request body read timeout |
| 409 | Another scrape owns the HTTP, database, or profile lock |
| 413 | Body exceeds 1 MiB |
| 415 | Nonempty body has the wrong content type |
| 500 | Unexpected server failure; details are logged server-side |
| 502 | Sync returned blocked/scrape/delivery failure; inspect `exit_code` |

Unknown HTTP methods use the stdlib's 501 response. Scrapes can take minutes;
client disconnect does not cancel work. Do not blindly retry POST after a
network timeout. Inspect state first. For long runs, use the CLI/job mode until
a durable asynchronous job API exists.

Machine-readable contract: [OpenAPI 3.1](../schemas/openapi.json). The spec is
checked into the repository; it is not served by an extra HTTP endpoint.

Completed targets refresh after the requested batch has no eligible unfinished
entries. This lets repeated `limit`-bounded calls finish later targets before
starting another refresh cycle.
