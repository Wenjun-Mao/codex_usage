"""A supervised owned process tree, independent of in-process timeout handlers."""
from math import isfinite
from contextlib import contextmanager
import signal
import sys
from time import perf_counter

from codex_usage.process_tree import run_process_tree

SECONDS = 600


@contextmanager
def catch_termination():
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def validate_process(value):
    if (not isinstance(value, dict) or set(value) != {
        "schema", "status", "seconds", "limit_seconds", "ownership"}
        or type(value["schema"]) is not int or value["schema"] != 1
        or value["status"] != "completed" or value["ownership"] != "owned-process-tree"
        or type(value["limit_seconds"]) is not int or value["limit_seconds"] != SECONDS
        or type(value["seconds"]) not in (int, float)
        or not 0 <= value["seconds"] < SECONDS or not isfinite(value["seconds"])):
        raise ValueError("Missing or unsuccessful bounded hover process proof")
    return value


def run_hover(command, *, environment, cwd):
    started = perf_counter()
    with catch_termination():
        result = run_process_tree(command, environment=environment, cwd=cwd, timeout_seconds=SECONDS)
    elapsed = perf_counter() - started
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    result.check_returncode()
    return validate_process({"schema": 1, "status": "completed", "seconds": elapsed,
        "limit_seconds": SECONDS, "ownership": "owned-process-tree"})
