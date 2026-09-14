import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

from grscraper import config, db, runner, sinks
from grscraper.locking import scrape_lock
from grscraper.models import Business, Review
from grscraper.resolver import CaptchaError
from grscraper.reviews import ReviewsPaneUnavailable
from grscraper.sync import sync


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "scraper.db")
    monkeypatch.setattr(config, "TARGETS", "")
    monkeypatch.setattr(config, "SINKS", "")
    db.init_db()
    return tmp_path


def seed(name, status="queued", retry_count=0):
    with db.connect() as conn:
        bid = db.insert_business(
            conn, Business(name, "name", status=status, retry_count=retry_count)
        )
    conn.close()
    return bid


@pytest.fixture
def browser(monkeypatch):
    @contextmanager
    def context(**kwargs):
        yield Mock()

    page = Mock()
    monkeypatch.setattr(runner, "browser_context", context)
    monkeypatch.setattr(runner, "new_page", lambda ctx: page)
    monkeypatch.setattr(runner, "_sleep_business_jitter", Mock())

    def resolve(page, biz):
        biz.status = "resolved"
        return biz

    monkeypatch.setattr(runner, "resolve", Mock(side_effect=resolve))
    html = (Path(__file__).parent / "fixtures/sample_cards.html").read_text()
    monkeypatch.setattr(runner, "collect_reviews_html", lambda *a, **k: (html, 2))
    return page


@pytest.fixture
def contexts(browser, monkeypatch):
    """Record every browser context the runner opens, with its profile dir."""
    opened = []

    @contextmanager
    def context(**kwargs):
        ctx = Mock(profile_dir=kwargs.get("profile_dir"))
        opened.append(ctx)
        yield ctx

    monkeypatch.setattr(runner, "browser_context", context)
    return opened


def test_interrupted_and_resolved_rows_navigate_again(state, browser):
    for status in ("resolving", "scraping", "resolved"):
        seed(status, status)
    result = runner.run()
    assert result["done"] == 3
    assert runner.resolve.call_count == 3
    assert browser.close.call_count == 3
    with db.connect() as conn:
        assert db.status_counts(conn) == {"done": 3}
    conn.close()


def test_unexpected_navigation_error_isolated_and_throttled(state, browser):
    seed("bad")
    seed("good")
    runner.resolve.side_effect = [RuntimeError("navigation failed"), None]
    result = runner.run()
    assert result["done"] == 1 and result["failed"] == 1
    runner._sleep_business_jitter.assert_called_once()
    assert browser.close.call_count == 2


def test_parser_error_does_not_strand_business(state, browser, monkeypatch):
    seed("bad")
    monkeypatch.setattr(runner, "parse_review_cards", Mock(side_effect=ValueError("bad DOM")))
    assert runner.run()["failed"] == 1
    with db.connect() as conn:
        assert db.status_counts(conn) == {"failed": 1}
    conn.close()


def test_sync_refreshes_only_requested_done_and_preserves_retry_budget(state, browser):
    seed("requested", "done")
    seed("unrelated", "done")
    seed("exhausted", "failed", config.MAX_RETRIES)
    seed("blocked", "blocked", 1)
    result = sync(raw_targets="requested")
    assert result["requeued"] == 1
    assert result["run"]["done"] == 1
    assert result["blocked_remaining"] == 1
    assert result["retries_exhausted"] == 1
    assert result["exit_code"] == 2
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT retry_count FROM businesses WHERE input_value='exhausted'"
            ).fetchone()[0]
            == config.MAX_RETRIES
        )
    conn.close()


def test_sync_no_refresh_and_exhausted_failures_are_nonzero(state, browser):
    seed("requested", "done")
    seed("exhausted", "failed", config.MAX_RETRIES)
    result = sync(raw_targets="requested", refresh=False)
    assert result["run"]["total"] == 0
    assert result["exit_code"] == 4


def test_foreign_key_failure_is_not_treated_as_duplicate(state):
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            db.upsert_review(conn, Review(review_id="missing", business_id=999))
    conn.close()


def test_sync_lock_is_reentrant_and_excludes_other_processes(state):
    code = """
from pathlib import Path
from grscraper import config
from grscraper.locking import scrape_lock, ScrapeBusyError
import sys
config.DB_PATH = Path(sys.argv[1])
config.BROWSER_PROFILE = Path(sys.argv[2])
try:
    with scrape_lock():
        sys.exit(1)
except ScrapeBusyError:
    sys.exit(0)
"""
    with scrape_lock(), scrape_lock():
        result = subprocess.run(
            [sys.executable, "-c", code, str(config.DB_PATH), str(config.BROWSER_PROFILE)],
            timeout=10,
        )
        assert result.returncode == 0
    with scrape_lock():
        pass


def test_lock_released_after_error(state):
    with pytest.raises(RuntimeError), scrape_lock():
        raise RuntimeError("failed")
    with scrape_lock():
        pass


def test_sink_oserror_does_not_prevent_other_deliveries(state, monkeypatch):
    original = sinks.deliver_one

    def deliver(payload, uri):
        if uri == "broken":
            raise PermissionError("not writable")
        return original(payload, uri)

    monkeypatch.setattr(sinks, "deliver_one", deliver)
    out = state / "out.json"
    result = sinks.deliver({"businesses": []}, ["broken", str(out)])
    assert result["delivered"] == [str(out)] and len(result["errors"]) == 1


def test_atomic_file_failure_preserves_previous_result(state, monkeypatch):
    out = state / "out.json"
    out.write_text('{"old": true}')
    monkeypatch.setattr(sinks.os, "replace", Mock(side_effect=OSError("disk failed")))
    result = sinks.deliver({"new": True}, [str(out)])
    assert result["errors"]
    assert out.read_text() == '{"old": true}'
    assert sorted(p.name for p in state.iterdir()) == ["out.json", "scraper.db"]


@pytest.mark.parametrize("limit", [0, -1, True, "1", 1.5])
def test_runner_rejects_invalid_limits(state, limit):
    with pytest.raises(ValueError):
        runner.run(limit=limit)


def test_cli_run_exits_nonzero_for_failures(state, browser):
    from grscraper import cli

    seed("bad")
    runner.resolve.side_effect = RuntimeError("navigation failed")
    assert cli.main(["run"]) == 4


def test_captcha_during_scroll_is_detected(monkeypatch):
    from grscraper import reviews
    from grscraper.resolver import CaptchaError

    page = Mock()
    monkeypatch.setattr(reviews, "is_captcha", Mock(side_effect=[False, True]))
    with pytest.raises(CaptchaError):
        reviews._scroll_load_all(page)
    assert page.evaluate.call_count == 1  # only scrolling, no count after CAPTCHA


def test_scrolling_deadline_stops_collection(monkeypatch):
    from grscraper import reviews

    monkeypatch.setattr(reviews, "is_captcha", lambda page: False)
    monkeypatch.setattr(config, "BUSINESS_TIMEOUT_S", 2)
    monkeypatch.setattr(reviews.time, "monotonic", Mock(side_effect=[0, 3]))
    page = Mock()
    with pytest.raises(TimeoutError):
        reviews._scroll_load_all(page)
    page.evaluate.assert_not_called()


def test_limited_sync_finishes_batch_before_refreshing(state, browser):
    first = sync(raw_targets="first;second", limit=1)
    second = sync(raw_targets="first;second", limit=1)
    assert first["run"]["done"] == second["run"]["done"] == 1
    assert [call.args[1].input_value for call in runner.resolve.call_args_list] == [
        "first",
        "second",
    ]
    assert sync(raw_targets="first;second", limit=1)["requeued"] == 2


def test_missing_reviews_pane_retries_on_a_fresh_context(state, contexts, monkeypatch):
    monkeypatch.setattr(config, "PANE_ATTEMPTS", 3)
    seed("degraded-twice")
    html = (Path(__file__).parent / "fixtures/sample_cards.html").read_text()
    monkeypatch.setattr(
        runner,
        "collect_reviews_html",
        Mock(
            side_effect=[
                ReviewsPaneUnavailable("Overview/About only"),
                ReviewsPaneUnavailable("Overview/About only"),
                (html, 3),
            ]
        ),
    )

    result = runner.run()

    assert result["done"] == 1 and result["failed"] == 0
    assert result["reviews_added"] == 3
    # Three distinct contexts: the bucket is drawn at context creation and a
    # reload or a new page inside the same one never re-rolls it.
    assert len({id(ctx) for ctx in contexts}) == 3
    # Attempt 1 keeps the persistent profile so consent survives; retries get a
    # throwaway user_data_dir, removed afterwards.
    assert contexts[0].profile_dir is None
    assert all(ctx.profile_dir is not None for ctx in contexts[1:])
    assert not any(ctx.profile_dir.exists() for ctx in contexts[1:])
    assert runner._sleep_business_jitter.call_count == 2


def test_exhausted_pane_attempts_are_one_queue_retry(state, contexts, monkeypatch):
    monkeypatch.setattr(config, "PANE_ATTEMPTS", 3)
    bid = seed("always-degraded")
    monkeypatch.setattr(
        runner,
        "collect_reviews_html",
        Mock(side_effect=ReviewsPaneUnavailable("Overview/About only")),
    )

    result = runner.run()

    assert result["done"] == 0 and result["failed"] == 1
    assert len(contexts) == 3
    # In-run context attempts are not queue retries; the row keeps its budget.
    with db.connect() as conn:
        row = conn.execute("SELECT status, retry_count FROM businesses").fetchone()
    conn.close()
    assert (row["status"], row["retry_count"]) == ("failed", 1)
    assert result["coverage"] == [
        {"business_id": bid, "collected": 0, "advertised": None, "ratio": None}
    ]


def test_captcha_is_never_retried_and_halts_the_run(state, contexts, monkeypatch):
    monkeypatch.setattr(config, "PANE_ATTEMPTS", 3)
    seed("captcha")
    seed("never-reached")
    monkeypatch.setattr(
        runner, "collect_reviews_html", Mock(side_effect=CaptchaError("captcha during reviews"))
    )

    result = runner.run()

    assert result["blocked"] is True and result["done"] == 0
    assert len(contexts) == 1
    with db.connect() as conn:
        assert db.status_counts(conn) == {"blocked": 1, "queued": 1}
    conn.close()


def test_coverage_reports_collected_against_advertised(state, browser):
    advertised = seed("advertised")
    unknown = seed("unknown")
    with db.connect() as conn:
        conn.execute("UPDATE businesses SET review_count=12 WHERE id=?", (advertised,))
        conn.commit()
    conn.close()

    result = runner.run()

    assert result["coverage"] == [
        {"business_id": advertised, "collected": 3, "advertised": 12, "ratio": 0.25},
        {"business_id": unknown, "collected": 3, "advertised": None, "ratio": None},
    ]
