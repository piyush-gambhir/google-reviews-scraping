import logging
import random
import time

from . import config
from .browser import browser_context, new_page
from .db import (
    connect,
    fetch_next_businesses,
    finish_run,
    start_run,
    transaction,
    update_business,
    upsert_review,
)
from .parser import parse_review_cards
from .resolver import CaptchaError, ResolveError, resolve
from .reviews import collect_reviews_html

log = logging.getLogger(__name__)


def _sleep_business_jitter() -> None:
    ms = random.randint(config.THROTTLE_BUSINESS_MIN_MS, config.THROTTLE_BUSINESS_MAX_MS)
    time.sleep(ms / 1000.0)


def run(workers: int = 1, limit: int | None = None, headless: bool = True) -> dict:
    """Single-worker queue processor (workers param reserved; v1 uses 1)."""
    if workers != 1:
        log.warning("workers > 1 is reserved for future versions; using 1")
    db = connect()
    queue = fetch_next_businesses(db, limit or 1_000_000)
    total = len(queue)
    if total == 0:
        return {"total": 0, "done": 0, "failed": 0, "blocked": False, "reviews_added": 0}

    run_id = start_run(db, workers=1, total=total)
    db.commit()

    done = 0
    failed = 0
    reviews_added = 0
    blocked = False
    notes: list[str] = []

    try:
        with browser_context(headless=headless) as ctx:
            for biz in queue:
                page = new_page(ctx)
                try:
                    if biz.status in ("queued", "failed"):
                        biz.status = "resolving"
                        with transaction(db):
                            update_business(db, biz)
                        try:
                            resolve(page, biz)
                        except CaptchaError:
                            blocked = True
                            biz.status = "blocked"
                            biz.status_reason = "captcha during resolve"
                            biz.retry_count += 1
                            with transaction(db):
                                update_business(db, biz)
                            notes.append(f"blocked at business id={biz.id}")
                            break
                        except ResolveError as e:
                            biz.status = "failed"
                            biz.status_reason = f"resolve: {e}"
                            biz.retry_count += 1
                            with transaction(db):
                                update_business(db, biz)
                            failed += 1
                            continue
                        else:
                            with transaction(db):
                                update_business(db, biz)

                    biz.status = "scraping"
                    with transaction(db):
                        update_business(db, biz)
                    try:
                        html, count = collect_reviews_html(page, expected=biz.review_count)
                    except CaptchaError:
                        blocked = True
                        biz.status = "blocked"
                        biz.status_reason = "captcha during reviews"
                        biz.retry_count += 1
                        with transaction(db):
                            update_business(db, biz)
                        notes.append(f"blocked at business id={biz.id}")
                        break
                    except Exception as e:
                        biz.status = "failed"
                        biz.status_reason = f"reviews: {e!r}"
                        biz.retry_count += 1
                        with transaction(db):
                            update_business(db, biz)
                        failed += 1
                        continue

                    parsed = parse_review_cards(html, biz.id)
                    inserted_for_biz = 0
                    with transaction(db):
                        for r in parsed:
                            if upsert_review(db, r):
                                inserted_for_biz += 1
                    reviews_added += inserted_for_biz
                    log.info(
                        "biz=%s parsed=%d inserted=%d expected=%s",
                        biz.id, len(parsed), inserted_for_biz, biz.review_count,
                    )

                    biz.status = "done"
                    biz.status_reason = None
                    with transaction(db):
                        update_business(db, biz)
                    done += 1
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                _sleep_business_jitter()
    finally:
        finish_run(
            db,
            run_id=run_id,
            done=done,
            failed=failed,
            reviews_added=reviews_added,
            notes="; ".join(notes) if notes else None,
        )
        db.commit()
        db.close()

    return {
        "total": total,
        "done": done,
        "failed": failed,
        "blocked": blocked,
        "reviews_added": reviews_added,
    }
