"""Single-host process lock for a database and its persistent browser profile.

Supported runtimes are Linux containers and macOS. State must live on a local
filesystem supporting advisory locks. This is not a distributed lease.
"""

import fcntl
import os
import threading
from contextlib import ExitStack, contextmanager
from functools import wraps

from . import config

_local = threading.local()


class ScrapeBusyError(RuntimeError):
    pass


@contextmanager
def scrape_lock():
    # sync() calls run() in the same thread; allow that nested acquisition.
    paths = tuple(
        sorted(
            {
                config.DB_PATH.resolve().with_suffix(".scrape.lock"),
                config.BROWSER_PROFILE.resolve().with_suffix(".scrape.lock"),
            }
        )
    )
    if getattr(_local, "owner", None) == (os.getpid(), paths):
        yield
        return
    with ExitStack() as stack:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open("a+b"))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ScrapeBusyError("a scrape is already using this database or profile") from exc
        _local.owner = (os.getpid(), paths)
        try:
            yield
        finally:
            _local.owner = None
    # Closing handles releases locks even on exceptions; process exit does too.


def exclusive_scrape(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with scrape_lock():
            return func(*args, **kwargs)

    return wrapped
