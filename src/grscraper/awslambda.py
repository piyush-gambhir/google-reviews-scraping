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
* **Ephemeral filesystem.** Only `/tmp` is writable, and it can survive warm invocations but is lost when the
  execution environment is replaced. That costs you cross-run dedupe and CAPTCHA-solve persistence.
  Use a durable single-worker runtime when persistent state is required;
  shared EFS state is not validated for this architecture.
"""

import logging
import os

os.environ.setdefault("GRS_DATA_DIR", "/tmp/grscraper")  # noqa: S108 - only writable path


def handler(event: dict | None = None, context: object | None = None) -> dict:
    logging.basicConfig(level=logging.INFO)
    from .request import ScrapeRequest

    request = ScrapeRequest.parse({} if event is None else event)
    return request.execute()
