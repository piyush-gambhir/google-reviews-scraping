"""AWS Lambda entrypoint.

    handler = grscraper.awslambda.handler

Event fields (all optional; env vars supply the defaults):

    {"targets": ["acme coffee roasters"], "sinks": ["s3://bucket/out.json"],
     "limit": 5, "inline_result": false}

Two Lambda-specific constraints worth knowing before you pick this target:

* **15-minute ceiling.** Default per-business throttle is 5-15s plus scroll
  time, so a handful of businesses per invocation is realistic and a large
  queue is not. Pass `limit` and invoke repeatedly, or use a container/job
  runtime for big batches.
* **Ephemeral filesystem.** Only `/tmp` is writable, and it does not survive
  between invocations, so the SQLite queue and browser profile start empty
  every time. That costs you cross-run dedupe and CAPTCHA-solve persistence.
  Point `GRS_DATA_DIR` at an EFS mount to keep them.
"""

import logging
import os

os.environ.setdefault("GRS_DATA_DIR", "/tmp/grscraper")  # noqa: S108 - only writable path


def handler(event: dict | None = None, context: object | None = None) -> dict:
    logging.basicConfig(level=logging.INFO)
    from .sync import sync

    event = event or {}

    targets = event.get("targets")
    if isinstance(targets, list):
        targets = "\n".join(str(t) for t in targets)

    sinks = event.get("sinks")
    if isinstance(sinks, str):
        sinks = [s.strip() for s in sinks.split(",") if s.strip()]

    result = sync(
        raw_targets=targets,
        sink_uris=sinks,
        limit=event.get("limit"),
        include_internal=bool(event.get("include_internal", False)),
    )
    payload = result.pop("payload")
    if event.get("inline_result"):
        result["result"] = payload
    return result
