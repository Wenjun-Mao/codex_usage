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
CONTROLS = {"scalar": "() => 1", "object": "() => ({visible:true,hidden:false,active:false,focusVisible:false,hover:true})",
    "clock": "() => ({entry_ms: performance.now(), time_origin: performance.timeOrigin})", "page-scalar": "1"}
DOCUMENT_STATE = "() => ({visibility: document.visibilityState, focused: document.hasFocus(), ready: document.readyState})"


@contextmanager
def observation_trace(observation, rows, *, renderer_clock=False, control="none", browsers=None, eval_lookup=None):
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
            row["page_url_before_observation"] = page.url
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
                            row["control_target"] = "page-literal" if control == "page-scalar" else "tooltip-handle"
                            target = page if control == "page-scalar" else tooltip
                            row["control_value"] = target.evaluate(CONTROLS[control])
                        finally:
                            mark("control-return")
                    mark("real-" + stage + "-entry")
                    if renderer_clock:
                        expression, *arguments = args
                        wrapped = """(tip, arg) => {
                            const before = performance.now();
                            const value = (EXPRESSION)(tip, arg);
                            return {value, entry_ms: before, time_origin: performance.timeOrigin,
                                elapsed_ms: performance.now() - before};
                        }""".replace("EXPRESSION", expression)
                        if eval_lookup is not None:
                            try:
                                snapshot_expression = eval_lookup.body_snapshot(page)
                            except Exception as error:
                                row["eval_lookup_failure"] = type(error).__name__ + ": " + str(error)[:1000]
                                snapshot_expression = "null"
                            if snapshot_expression != "null":
                                safe_snapshot = "(() => { try { return " + snapshot_expression + "; } catch { return null; } })()"
                                wrapped = wrapped.replace("elapsed_ms: performance.now() - before",
                                    "elapsed_ms: performance.now() - before, eval_lookup: " + safe_snapshot)
                        result = tooltip.evaluate(wrapped, *arguments, **options)
                        read = {
                            "stage": stage, "elapsed_ms": result["elapsed_ms"],
                            "entry_ms": result.get("entry_ms"), "time_origin": result.get("time_origin")}
                        if eval_lookup is not None:
                            if "eval_lookup" in result:
                                read["eval_lookup"] = result["eval_lookup"]
                            try:
                                eval_lookup.validate(page, result.get("eval_lookup"), read["entry_ms"], read["time_origin"])
                            except Exception as error:
                                row["eval_lookup_failure"] = type(error).__name__ + ": " + str(error)[:1000]
                        row.setdefault("renderer_reads", []).append(read)
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
            value = original(page, StyleObserver(), real_input, **kwargs)
            if "eval_lookup_failure" in row:
                raise RuntimeError("Eval lookup diagnostic unavailable: " + row["eval_lookup_failure"])
            return value
        except BaseException as error:
            row["failure"] = type(error).__name__ + ": " + str(error)[:4000]
            if "eval_lookup_failure" in row:
                error.add_note("Eval lookup diagnostic unavailable: " + row["eval_lookup_failure"])
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
    parser.add_argument("--process-sample", action="store_true",
        help="Bounded external sampling on the ephemeral macOS diagnostic runner only")
    parser.add_argument("--eval-lookup", choices=("none", "descriptor", "clock"), default="none",
        help="Nonqualifying public eval property lookup marker or unchanged-descriptor control")
    args = parser.parse_args()
    if args.eval_lookup != "none" and (not args.renderer_clock or args.control != "none" or args.process_sample):
        parser.error("Eval lookup requires renderer clock, no timed control and no sampling")
    sys.path.insert(0, str(SCRIPTS))
    from verification import hover_observation
    args.output.mkdir(parents=True, exist_ok=True)
    rows, browsers, documents = [], {}, []
    eval_lookup = None
    if args.eval_lookup != "none":
        from probes.eval_lookup_marker import EvalLookupMarker
        eval_lookup = EvalLookupMarker(args.eval_lookup, documents)
    evidence = {"diagnostic_only": True, "deadline_ms": 250, "control": args.control,
        "extra_dom_reads_per_expression": 0,
        "untimed_document_state_reads_per_observation": 3 if args.renderer_clock else 0,
        "extra_control_queries_per_timed_read": 0 if args.control == "none" else 1,
        "control_target": "none" if args.control == "none" else (
            "page-literal" if args.control == "page-scalar" else "tooltip-handle"),
        "script_injection": args.renderer_clock or args.control != "none", "product_scripts_disabled": True,
        "instrumentation_overhead_calibrated": False,
        "external_process_sampling": args.process_sample,
        "eval_lookup_mode": args.eval_lookup, "eval_lookup_documents": documents,
        "eval_lookup_extra_queries_per_webkit_document": 0 if eval_lookup is None else 2,
        "eval_lookup_target_receipt_marker": False,
        "platform": platform.platform(), "calls": rows}
    original_argv = sys.argv
    sys.argv = [str(SCRIPTS / "check_breakdown_hover_ui.py"), "--output", str(args.output)]
    primary_error = None
    try:
        from probes.webkit_process_sample import sampling
        with sampling(args.output / "samples", args.process_sample) as sample_status, observation_trace(
            hover_observation, rows, renderer_clock=args.renderer_clock, control=args.control,
            browsers=browsers, eval_lookup=eval_lookup):
            evidence["process_sampling_status"] = sample_status
            if eval_lookup is None:
                runpy.run_path(sys.argv[0], run_name="__main__")
            else:
                runpy.run_path(sys.argv[0], run_name="__main__",
                    init_globals={"diagnostic_document": eval_lookup.document})
        evidence["replay_passed"] = True
    except BaseException as error:
        primary_error = error
        evidence["replay_passed"] = False
        evidence["failure"] = type(error).__name__ + ": " + str(error)[:4000]
        raise
    finally:
        sys.argv = original_argv
        try:
            from probes.browser_provenance import collect
            try:
                evidence["provenance"] = collect(browsers)
            except Exception as error:
                evidence["provenance_failure"] = str(error)[:1000]
            (args.output / "input-timings.json").write_text(json.dumps(evidence, indent=2) + "\n")
        except BaseException as diagnostic_error:
            if primary_error is None:
                raise
            primary_error.add_note("Diagnostic evidence could not be retained: " + str(diagnostic_error)[:1000])


if __name__ == "__main__":
    main()
