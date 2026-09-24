"""Short, process-safe transactions for local financial/task JSON ledgers."""
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def ledger_lock(path: Path):
    # flock is released by the OS on process death; no stale-lock time guess.
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + '.lock').open('a') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
