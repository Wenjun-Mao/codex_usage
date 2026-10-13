"""Collect every selected case once, using the pinned pytest JUnit address codec."""
import json
from pathlib import Path
import platform

from _pytest.junitxml import mangle_test_address

_collection = []


def pytest_addoption(parser):
    parser.addoption("--qualification-inventory", default=None)
    parser.addoption("--qualification-scope", choices=("core", "metadata"), default="core")


def pytest_collection_finish(session):
    _collection.clear()
    for item in session.items:
        address = mangle_test_address(item.nodeid)
        _collection.append([".".join(address[:-1]), address[-1]])


def pytest_sessionfinish(session, exitstatus):
    output = session.config.getoption("--qualification-inventory")
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": 1, "scope": session.config.getoption("--qualification-scope"),
            "exitstatus": int(exitstatus), "platform": platform.system(), "collected": sorted(_collection)},
            separators=(",", ":")) + "\n")
