"""One-shot sync: enqueue targets, scrape, deliver.

This is the entrypoint a scheduler calls. The four-step local workflow
(init / ingest / run / export) collapses into a single idempotent command that
needs no interactive state and no files on disk.
"""

import logging
from contextlib import closing

from . import config, snapshot
from .db import connect as db_connect
from .db import init_db, reset_status
from .locking import exclusive_scrape
from .sinks import deliver, parse_sinks
from .targets import ingest_targets, parse_targets
from .url import classify_input

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2
EXIT_SINK_FAILED = 3
EXIT_SCRAPE_FAILED = 4


@exclusive_scrape
def sync(
    raw_targets: str | None = None,
    sink_uris: list[str] | None = None,
    *,
    headless: bool = True,
    limit: int | None = None,
    retry_blocked: bool = False,
    refresh: bool = True,
    only_done: bool = False,
    include_internal: bool = False,
) -> dict:
    """Run a full sync and return a result dict.

    Requested completed businesses are refreshed by default. Failed businesses
    retain their retry budget; CAPTCHA-blocked businesses require explicit retry.
    The payload remains a snapshot of the whole operator-owned database.
    """
    from .runner import run as run_queue

    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")
    init_db()

    raw = raw_targets if raw_targets is not None else config.TARGETS
    targets = parse_targets(raw)
    ingested = ingest_targets(targets) if targets else {"inserted": 0, "skipped": 0}
    log.info(
        "targets=%d inserted=%d skipped=%d",
        len(targets),
        ingested["inserted"],
        ingested["skipped"],
    )

    requeued = 0
    with closing(db_connect()) as conn, conn:
        # Finish the requested batch before starting another refresh cycle.
        # Otherwise repeated limit=1 calls keep requeueing the first done row
        # and starve every later target.
        pending_targets = any(
            conn.execute(
                "SELECT 1 FROM businesses WHERE input_value=? AND input_type=? "
                "AND status IN ('queued', 'resolved', 'resolving', 'scraping', 'failed') "
                "AND retry_count < ?",
                (value, declared or classify_input(value), config.MAX_RETRIES),
            ).fetchone()
            for value, declared in targets
        )
        if refresh and not pending_targets:
            for value, declared in targets:
                cur = conn.execute(
                    "UPDATE businesses SET status='queued', retry_count=0, status_reason=NULL "
                    "WHERE input_value=? AND input_type=? AND status='done'",
                    (value, declared or classify_input(value)),
                )
                requeued += cur.rowcount
        if retry_blocked:
            requeued += reset_status(conn, from_status="blocked", to_status="queued")

    run_result = run_queue(workers=1, limit=limit, headless=headless)
    log.info("run: %s", run_result)

    payload = snapshot.build(run_result, only_done=only_done, include_internal=include_internal)

    uris = sink_uris if sink_uris is not None else parse_sinks(config.SINKS)
    delivery = deliver(payload, uris) if uris else {"delivered": [], "errors": []}

    with closing(db_connect()) as conn:
        blocked_remaining = conn.execute(
            "SELECT COUNT(*) FROM businesses WHERE status='blocked'"
        ).fetchone()[0]
        exhausted = conn.execute(
            "SELECT COUNT(*) FROM businesses WHERE status='failed' AND retry_count>=?",
            (config.MAX_RETRIES,),
        ).fetchone()[0]
    if run_result["blocked"] or blocked_remaining:
        exit_code = EXIT_BLOCKED
    elif run_result["failed"] or exhausted:
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
        "blocked_remaining": blocked_remaining,
        "retries_exhausted": exhausted,
        "payload": payload,
    }
