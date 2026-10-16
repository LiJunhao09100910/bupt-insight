from contextlib import contextmanager
from pathlib import Path

from core.errors import InsightError


@contextmanager
def single_run(path):
    """OS lock is released even after a crash. Covers sync AND outbox dispatch."""
    import sys
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    file = open(path, "a+b")
    if Path(path).stat().st_size == 0:
        file.write(b"0")
        file.flush()
    file.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        file.close()
        raise InsightError("already_running", "另一个采集/推送任务正在运行") from None
    try:
        yield
    finally:
        file.close()
