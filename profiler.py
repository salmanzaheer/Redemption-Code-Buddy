"""
Profiling and logging helpers for the redemption code buddy.

- setup_logging / set_logging_enabled : file logging that can be toggled at runtime
- @timed                              : decorator that times a function, logs it and records stats
- Timer                               : context manager for timing any block of code
- get_stats / format_report / reset   : aggregated per-function timing statistics
"""

import functools
import logging
import threading
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "codegen"
logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())

DEFAULT_LOG_FILE = Path(__file__).resolve().parent / "logs" / "codegen.log"
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"


# logging
def setup_logging(
    enabled=True, log_file=DEFAULT_LOG_FILE, level=logging.DEBUG, console=False
):
    """Configure the 'codegen' logger. Safe to call more than once."""
    shutdown_logging()
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler._codegen = True
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        stream._codegen = True
        logger.addHandler(stream)

    logger.setLevel(level)
    logger.propagate = False
    logger.disabled = not enabled
    return log_file


def shutdown_logging():
    """Remove and close handlers added by setup_logging (releases the log file)."""
    for handler in list(logger.handlers):
        if getattr(handler, "_codegen", False):
            logger.removeHandler(handler)
            handler.close()


def set_logging_enabled(enabled: bool):
    logger.disabled = not enabled


def is_logging_enabled() -> bool:
    return not logger.disabled


# formatting
def format_duration(seconds: float) -> str:
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f} µs"
    if seconds < 1:
        return f"{seconds * 1000:.2f} ms"
    if seconds < 60:
        return f"{seconds:.3f} s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)} min {rest:.1f} s"


# statistics
@dataclass
class FunctionStats:
    calls: int = 0
    total: float = 0.0
    minimum: float = float("inf")
    maximum: float = 0.0
    last: float = 0.0

    @property
    def average(self) -> float:
        return self.total / self.calls if self.calls else 0.0


_stats: dict[str, FunctionStats] = {}
_lock = threading.Lock()


def record(label: str, elapsed: float):
    with _lock:
        s = _stats.setdefault(label, FunctionStats())
        s.calls += 1
        s.total += elapsed
        s.minimum = min(s.minimum, elapsed)
        s.maximum = max(s.maximum, elapsed)
        s.last = elapsed


def get_stats() -> dict[str, FunctionStats]:
    with _lock:
        return {
            k: FunctionStats(v.calls, v.total, v.minimum, v.maximum, v.last)
            for k, v in _stats.items()
        }


def reset_stats():
    with _lock:
        _stats.clear()


def format_report() -> str:
    stats = get_stats()
    if not stats:
        return "No timing data recorded yet."
    width = max(len(k) for k in stats) + 2
    header = f"{'Function':<{width}}{'Calls':>7}{'Total':>12}{'Avg':>12}{'Min':>12}{'Max':>12}{'Last':>12}"
    lines = [header, "-" * len(header)]
    for label, s in sorted(stats.items(), key=lambda kv: kv[1].total, reverse=True):
        lines.append(
            f"{label:<{width}}{s.calls:>7}{format_duration(s.total):>12}"
            f"{format_duration(s.average):>12}{format_duration(s.minimum):>12}"
            f"{format_duration(s.maximum):>12}{format_duration(s.last):>12}"
        )
    return "\n".join(lines)


# timing tools
def timed(func=None, *, name=None, level=logging.DEBUG):
    """
    Decorator: measure execution time, log it and record statistics.
    Use as @timed or @timed(name="custom label", level=logging.INFO).
    Timing is recorded even if the function raises.
    """

    def decorator(fn):
        label = name or f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                record(label, elapsed)
                logger.log(level, "%s took %s", label, format_duration(elapsed))

        wrapper.timing_label = label
        return wrapper

    return decorator(func) if func is not None else decorator


class Timer:
    """
    Context manager for timing a block:

        with Timer("generate") as t:
            ...
        print(t.elapsed, t.pretty)
    """

    def __init__(self, label="block", log=True, record_stats=False, level=logging.INFO):
        self.label = label
        self.log = log
        self.record_stats = record_stats
        self.level = level
        self._start = None
        self._end = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._end = time.perf_counter()
        if self.record_stats:
            record(self.label, self.elapsed)
        if self.log:
            logger.log(self.level, "%s took %s", self.label, self.pretty)
        return False

    @property
    def elapsed(self) -> float:
        if self._start is None:
            return 0.0
        end = self._end if self._end is not None else time.perf_counter()
        return end - self._start

    @property
    def pretty(self) -> str:
        return format_duration(self.elapsed)
