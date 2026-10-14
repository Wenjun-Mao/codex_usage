"""Diagnostic-only markers around unchanged real input/style calls and guards."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import runpy
import sys
from time import perf_counter

SCRIPTS = Path(__file__).resolve().parents[1]
CONTROLS = {"scalar": "() => 1", "object": "() => ({visible:true,hidden:false,active:false,focusVisible:false,hover:true})"}
DOCUMENT_STATE = "() => ({visibility: document.visibilityState, focused: document.hasFocus(), ready: document.readyState})"


@contextmanager
def observation_trace(observation, rows, *, renderer_clock=False, control="none", browsers=None):
    original = observation.observe_input

    def traced(page, tooltip, action, **kwargs):
        if browsers is not None and hasattr(page, "context"):
            browser = page.context.browser
            kind = browser.browser_type
            browsers.setdefault(kind.name, {"version": browser.version,
                "configured_executable": kind.executable_path})
        row = {"phase": kwargs["phase"], "utc": datetime.now(timezone.utc).isoformat(), "calls": []}
        if renderer_clock and page is not None and hasattr(page, "evaluate"):
            row["document_state_before_observation"] = page.evaluate(DOCUMENT_STATE)
        started = perf_counter()
        input_started = False

        def mark(stage):
            row["calls"].append({"stage": stage, "ms": (perf_counter() - started) * 1000})

        class StyleObserver:
            def evaluate(self, *args, **options):
                stage = "style" if input_started else "baseline"
                mark(stage + "-entry")
                try:
                    if input_started and control != "none":
                        mark("control-entry")
                        try:
                            row["control_value"] = tooltip.evaluate(CONTROLS[control])
                        finally:
                            mark("control-return")
                    mark("real-" + stage + "-entry")
                    if renderer_clock:
                        expression, *arguments = args
                        wrapped = """(tip, arg) => {
                            const before = performance.now();
                            const value = (EXPRESSION)(tip, arg);
                            return {value, elapsed_ms: performance.now() - before};
                        }""".replace("EXPRESSION", expression)
                        result = tooltip.evaluate(wrapped, *arguments, **options)
                        row.setdefault("renderer_reads", []).append({
                            "stage": stage, "elapsed_ms": result["elapsed_ms"]})
                        return result["value"]
                    return tooltip.evaluate(*args, **options)
                finally:
                    mark(stage + "-return")

        def real_input():
            nonlocal input_started
            input_started = True
            mark("input-entry")
            try:
                return action()
            finally:
                mark("input-return")

        try:
            return original(page, StyleObserver(), real_input, **kwargs)
        except BaseException as error:
            row["failure"] = type(error).__name__ + ": " + str(error)[:4000]
            raise
        finally:
            mark("observation-return")
            rows.append(row)

    observation.observe_input = traced
    try:
        yield
    finally:
        observation.observe_input = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--renderer-clock", action="store_true",
        help="Diagnostic-only test-side performance clock around each original style expression")
    parser.add_argument("--control", choices=("none", *CONTROLS), default="none",
        help="Extra non-DOM query before each timed style read; never qualification")
    args = parser.parse_args()
    sys.path.insert(0, str(SCRIPTS))
    from verification import hover_observation
    args.output.mkdir(parents=True, exist_ok=True)
    rows, browsers = [], {}
    evidence = {"diagnostic_only": True, "deadline_ms": 250, "control": args.control,
        "extra_dom_reads_per_expression": 0,
        "untimed_document_state_reads_per_observation": 3 if args.renderer_clock else 0,
        "extra_control_queries_per_timed_read": 0 if args.control == "none" else 1,
        "script_injection": args.renderer_clock or args.control != "none", "product_scripts_disabled": True,
        "instrumentation_overhead_calibrated": False,
        "platform": platform.platform(), "calls": rows}
    original_argv = sys.argv
    sys.argv = [str(SCRIPTS / "check_breakdown_hover_ui.py"), "--output", str(args.output)]
    try:
        with observation_trace(hover_observation, rows, renderer_clock=args.renderer_clock,
            control=args.control, browsers=browsers):
            runpy.run_path(sys.argv[0], run_name="__main__")
        evidence["replay_passed"] = True
    except BaseException as error:
        evidence["replay_passed"] = False
        evidence["failure"] = type(error).__name__ + ": " + str(error)[:4000]
        raise
    finally:
        sys.argv = original_argv
        from probes.browser_provenance import collect
        try:
            evidence["provenance"] = collect(browsers)
        except Exception as error:
            evidence["provenance_failure"] = str(error)[:1000]
        (args.output / "input-timings.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
