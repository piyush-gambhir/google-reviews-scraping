import logging
import random
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from . import config
from .browser import browser_context, new_page
from .db import (
    connect,
    fetch_next_businesses,
    finish_run,
    recover_interrupted,
    start_run,
    transaction,
    update_business,
    upsert_review,
)
from .locking import exclusive_scrape
from .parser import parse_review_cards
from .resolver import CaptchaError, ResolveError, resolve
from .reviews import ReviewsPaneUnavailable, collect_reviews_html
from .url import maps_reviews_url

log = logging.getLogger(__name__)


def _sleep_business_jitter() -> None:
    ms = random.randint(config.THROTTLE_BUSINESS_MIN_MS, config.THROTTLE_BUSINESS_MAX_MS)
    time.sleep(ms / 1000.0)


@contextmanager
def _attempt_context(attempt: int, headless: bool):
    """One browser context for one attempt at one business.

    Attempt 0 uses the persistent profile so cookies and consent carry over
    between runs. Later attempts get a throwaway profile: a context that drew
    the cut-down place panel never recovers, and the re-roll was only ever
    observed against a user_data_dir Google had not seen before.
    """
    if attempt == 0:
        with browser_context(headless=headless) as ctx:
            yield ctx
        return
    profile_dir = Path(tempfile.mkdtemp(prefix="grs-profile-"))
    try:
        with browser_context(headless=headless, profile_dir=profile_dir) as ctx:
            yield ctx
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


def _coverage_entry(business_id: int | None, collected: int, advertised: int | None) -> dict:
    """How much of what Google advertises this run actually came back.

    Free-tier scraping is partial by nature, so the result has to say so rather
    than let a caller read `done` as complete. A place advertising no reviews
    has no meaningful ratio.
    """
    ratio = round(collected / advertised, 3) if advertised else None
    return {
        "business_id": business_id,
        "collected": collected,
        "advertised": advertised,
        "ratio": ratio,
    }


@exclusive_scrape
def run(workers: int = 1, limit: int | None = None, headless: bool = True) -> dict:
    """Single-worker queue processor (workers param reserved; v1 uses 1)."""
    if workers != 1:
        log.warning("workers > 1 is reserved for future versions; using 1")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")
    db = connect()
    try:
        recover_interrupted(db)
        db.commit()
        queue = fetch_next_businesses(db, limit if limit is not None else 1_000_000)
    except BaseException:
        db.close()
        raise
    total = len(queue)
    if total == 0:
        db.close()
        return {
            "total": 0,
            "done": 0,
            "failed": 0,
            "blocked": False,
            "reviews_added": 0,
            "coverage": [],
        }

    try:
        run_id = start_run(db, workers=1, total=total)
        db.commit()
    except BaseException:
        db.close()
        raise

    done = 0
    failed = 0
    reviews_added = 0
    blocked = False
    notes: list[str] = []
    coverage: list[dict] = []

    try:
        for index, biz in enumerate(queue):
            if index:
                _sleep_business_jitter()
            original_fingerprint = biz.place_fingerprint
            # Decided once per business: an attempt on a new context starts from
            # a blank page, so it has to redo the navigation that resolved it.
            needs_resolve = biz.status in ("queued", "failed", "resolved")
            collected = 0

            # One context per attempt, not one per run. Whether Maps serves the
            # full place panel or the cut-down Overview/About one is drawn when
            # the context is created and never re-rolls inside it, so a single
            # context around the whole queue let one bad draw fail every
            # business in the run.
            for attempt in range(config.PANE_ATTEMPTS):
                if attempt:
                    _sleep_business_jitter()
                page = None
                try:
                    with _attempt_context(attempt, headless=headless) as ctx:
                        page = new_page(ctx)
                        if needs_resolve:
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
                                break
                            else:
                                with transaction(db):
                                    update_business(db, biz)

                        biz.status = "scraping"
                        with transaction(db):
                            update_business(db, biz)
                        try:
                            html, count = collect_reviews_html(
                                page,
                                expected=biz.review_count,
                                reviews_url=maps_reviews_url(
                                    biz.place_fingerprint, biz.latitude, biz.longitude
                                ),
                            )
                        except CaptchaError:
                            # Never retried. A CAPTCHA means Google has decided
                            # about this client, and more contexts only dig in.
                            blocked = True
                            biz.status = "blocked"
                            biz.status_reason = "captcha during reviews"
                            biz.retry_count += 1
                            with transaction(db):
                                update_business(db, biz)
                            notes.append(f"blocked at business id={biz.id}")
                            break
                        except ReviewsPaneUnavailable as e:
                            # The one failure a fresh context can actually fix.
                            if attempt + 1 < config.PANE_ATTEMPTS:
                                log.warning(
                                    "biz=%s no reviews pane, retrying on a fresh context (%d/%d)",
                                    biz.id,
                                    attempt + 1,
                                    config.PANE_ATTEMPTS,
                                )
                                continue
                            biz.status = "failed"
                            biz.status_reason = f"reviews: {e!r}"
                            biz.retry_count += 1
                            with transaction(db):
                                update_business(db, biz)
                            failed += 1
                            break
                        except Exception as e:
                            biz.status = "failed"
                            biz.status_reason = f"reviews: {e!r}"
                            biz.retry_count += 1
                            with transaction(db):
                                update_business(db, biz)
                            failed += 1
                            break

                        parsed = parse_review_cards(html, biz.id)
                        collected = len(parsed)
                        inserted_for_biz = 0
                        with transaction(db):
                            for r in parsed:
                                if upsert_review(db, r):
                                    inserted_for_biz += 1
                        reviews_added += inserted_for_biz
                        log.info(
                            "biz=%s parsed=%d inserted=%d expected=%s",
                            biz.id,
                            len(parsed),
                            inserted_for_biz,
                            biz.review_count,
                        )

                        # Zero cards off a resolved place page is a scrape failure,
                        # not an empty business. It means the reviews pane never
                        # rendered — bot detection, or selectors that need updating.
                        # Recording it as `done` would let a scheduled run report
                        # success while delivering nothing, which is the one failure
                        # mode nobody notices.
                        if not parsed:
                            biz.status = "failed"
                            biz.status_reason = (
                                "resolved the place but extracted 0 review cards "
                                "(bot detection or stale selectors)"
                            )
                            biz.retry_count += 1
                            with transaction(db):
                                update_business(db, biz)
                            failed += 1
                            log.error("biz=%s resolved but yielded no reviews", biz.id)
                            break

                        biz.status = "done"
                        biz.status_reason = None
                        with transaction(db):
                            update_business(db, biz)
                        done += 1
                        break
                except Exception as exc:
                    # Navigation, parsing, page creation and persistence failures
                    # must not strand a row or discard the rest of the queue.
                    log.exception("business %s failed", biz.id)
                    biz.place_fingerprint = original_fingerprint
                    biz.status = "failed"
                    biz.status_reason = f"business: {exc!r}"
                    biz.retry_count += 1
                    with transaction(db):
                        update_business(db, biz)
                    failed += 1
                    break
                finally:
                    try:
                        if page is not None:
                            page.close()
                    except Exception:
                        pass

            entry = _coverage_entry(biz.id, collected, biz.review_count)
            coverage.append(entry)
            log.info(
                "biz=%s collected=%d advertised=%s coverage=%s",
                biz.id,
                collected,
                entry["advertised"],
                entry["ratio"],
            )
            if blocked:
                break
    except BaseException as exc:
        notes.append(f"run interrupted: {type(exc).__name__}")
        raise
    finally:
        try:
            finish_run(
                db,
                run_id=run_id,
                done=done,
                failed=failed,
                reviews_added=reviews_added,
                notes="; ".join(notes) if notes else None,
            )
            db.commit()
        finally:
            db.close()

    return {
        "total": total,
        "done": done,
        "failed": failed,
        "blocked": blocked,
        "reviews_added": reviews_added,
        "coverage": coverage,
    }
