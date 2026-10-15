"""Incremental synthetic case journals; failures never become passing receipts."""
from contextlib import contextmanager, nullcontext
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
from time import perf_counter

from .visual_cases import ASSERTIONS, case_key, validate_inventory


def case_context(audit, page, case):
    return audit.case(page, case) if audit is not None else nullcontext()


class VisualEvidence:
    def __init__(self, output, suite, *, synthetic_only=True):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.started = perf_counter()
        self.data = {"schema": 2 if suite == "hover" else 1, "suite": suite, "status": "incomplete",
            "synthetic_only": synthetic_only, "completed": [], "current": None,
            "assertions": list(ASSERTIONS[suite]), "documents": {},
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                "playwright": version("playwright")},
            "origin": {key: os.environ.get(key, "") for key in
                ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")}}
        self.save()

    def save(self):
        self.data["wall_seconds"] = perf_counter() - self.started
        target = self.output / "verification.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(target)

    def document(self, label, contents):
        from hashlib import sha256
        self.data["documents"][label] = sha256(contents.encode()).hexdigest()

    def check(self, page, case, callback, *args):
        with self.case(page, case):
            return callback(*args)

    @contextmanager
    def case(self, page, case):
        self.data["current"] = case
        self.save()
        try:
            if os.environ.get("CODEX_VISUAL_FAIL_CASE") == case_key(case):
                raise AssertionError("Requested synthetic qualification failure")
            yield
        except BaseException as error:
            self.fail(error, page)
            raise
        else:
            self.data["completed"].append(case)
            self.data["current"] = None
            self.save()

    def fail(self, error, page=None):
        self.data["status"] = "failed"
        self.data["failure"] = {"type": type(error).__name__, "message": str(error)[:4000]}
        if page is not None:
            try:
                self.data["failure"]["dom"] = page.evaluate("""() => ({
                    focus: document.activeElement?.outerHTML?.slice(0, 1000),
                    hovered: [...document.querySelectorAll(':hover')].slice(-6).map(e => ({
                        tag: e.tagName, class: e.getAttribute('class'),
                        visibility: getComputedStyle(e).visibility, opacity: getComputedStyle(e).opacity,
                        display: getComputedStyle(e).display, rect: e.getBoundingClientRect().toJSON()})),
                    tooltips: [...document.querySelectorAll('.ub-hover-tooltip')].slice(0, 10).map(e => ({
                        visibility: getComputedStyle(e).visibility, opacity: getComputedStyle(e).opacity,
                        focused: e.closest('.ub-hover-bucket')?.matches(':focus-within'),
                        display: getComputedStyle(e).display,
                        rect: e.getBoundingClientRect().toJSON()})),
                    hit: document.elementFromPoint(1, 1)?.tagName
                })""")
                page.screenshot(path=str(self.output / "failure.png"), timeout=3000)
            except Exception as diagnostic_error:
                self.data["failure"]["diagnostic_error"] = str(diagnostic_error)[:1000]
        self.save()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if error is not None:
            if self.data["status"] != "failed":
                self.fail(error)
            return False
        if not self.data["synthetic_only"]:
            self.data["status"] = "diagnostic-only"
            self.save()
            return False
        self.data["status"] = "functional-complete" if self.data["suite"] == "hover" else "passed"
        try:
            validate_inventory(self.data, self.data["suite"])
        except Exception as error:
            self.fail(error)
            raise
        self.save()
        return False
