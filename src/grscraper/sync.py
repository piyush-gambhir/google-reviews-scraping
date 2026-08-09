"""One-shot sync: enqueue targets, scrape, deliver.

This is the entrypoint a scheduler calls. The four-step local workflow
(init / ingest / run / export) collapses into a single idempotent command that
needs no interactive state and no files on disk.
"""

import logging

from . import config, snapshot
from .db import connect as db_connect
from .db import init_db, reset_status
from .sinks import deliver, parse_sinks
from .targets import ingest_targets, parse_targets

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2
EXIT_SINK_FAILED = 3
EXIT_SCRAPE_FAILED = 4


def sync(
    raw_targets: str | None = None,
    sink_uris: list[str] | None = None,
    *,
    headless: bool = True,
    limit: int | None = None,
    retry_blocked: bool = True,
    only_done: bool = False,
    include_internal: bool = False,
) -> dict:
    """Run a full sync and return a result dict.

    Re-running is safe: businesses already `done` are not re-queued by
    `insert_business`, and reviews dedupe on `data-review-id`. A run that ended
    `blocked` or `failed` last time is requeued by default, which is what makes
    an unattended weekly schedule self-healing.
    """
    from .runner import run as run_queue

    init_db()

    raw = raw_targets if raw_targets is not None else config.TARGETS
    targets = parse_targets(raw)
    ingested = ingest_targets(targets) if targets else {"inserted": 0, "skipped": 0}
    log.info(
        "targets=%d inserted=%d skipped=%d",
        len(targets), ingested["inserted"], ingested["skipped"],
    )

    requeued = 0
    if retry_blocked:
        with db_connect() as conn:
            for status in ("blocked", "failed"):
                requeued += reset_status(conn, from_status=status, to_status="queued")
            conn.commit()
        if requeued:
            log.info("requeued %d previously blocked/failed businesses", requeued)

    run_result = run_queue(workers=1, limit=limit, headless=headless)
    log.info("run: %s", run_result)

    payload = snapshot.build(
        run_result, only_done=only_done, include_internal=include_internal
    )

    uris = sink_uris if sink_uris is not None else parse_sinks(config.SINKS)
    delivery = deliver(payload, uris) if uris else {"delivered": [], "errors": []}

    if run_result["blocked"]:
        exit_code = EXIT_BLOCKED
    elif run_result["failed"]:
        # Surface partial failures. Exiting 0 here would let a weekly schedule
        # look healthy forever while quietly scraping nothing.
        exit_code = EXIT_SCRAPE_FAILED
    elif delivery["errors"]:
        exit_code = EXIT_SINK_FAILED
    else:
        exit_code = EXIT_OK

    return {
        "targets": len(targets),
        "ingested": ingested,
        "requeued": requeued,
        "run": run_result,
        "delivery": delivery,
        "businesses": len(payload["businesses"]),
        "reviews": sum(len(b["reviews"]) for b in payload["businesses"]),
        "exit_code": exit_code,
        "payload": payload,
    }
