"""Observe existing native CDP calls without changing replay or its 250ms guard."""
import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import platform
import runpy
import sys
from time import perf_counter

SCRIPTS = Path(__file__).resolve().parents[1]


@contextmanager
def protocol_trace(target_type, rows):
    original_send, original_received = target_type.send, target_type._received
    active = {}
    started = perf_counter()

    def milliseconds():
        return (perf_counter() - started) * 1000

    def received(target, event):
        if event.get("sessionId") == target.session_id:
            message = json.loads(event["message"])
            row = active.get((id(target), message.get("id")))
            if row is not None:
                row["iframe_reply_ms"] = milliseconds()
        return original_received(target, event)

    def send(target, method, params=None):
        row = {"method": method, "started_ms": milliseconds()}
        key = (id(target), target.sequence + 1)
        active[key] = row
        session_send = target.session.send

        def outer_send(name, parameters=None):
            result = session_send(name, parameters)
            if name == "Target.sendMessageToTarget":
                row["outer_ack_ms"] = milliseconds()
            return result

        target.session.send = outer_send
        try:
            result = original_send(target, method, params)
            if method == "CSS.getComputedStyleForNode":
                row["style"] = {item["name"]: item["value"] for item in result["computedStyle"]
                    if item["name"] in ("visibility", "opacity")}
            return result
        except BaseException as error:
            row["failure"] = type(error).__name__ + ": " + str(error)[:1000]
            raise
        finally:
            row["completed_ms"] = milliseconds()
            rows.append(row)
            active.pop(key, None)
            target.session.send = session_send

    target_type.send, target_type._received = send, received
    try:
        yield
    finally:
        target_type.send, target_type._received = original_send, original_received


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("plain", "traced"), required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--vsix", type=Path, required=True)
    parser.add_argument("--qualification-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(SCRIPTS))
    from speed_native_target import NativeSpeedTarget
    from contextlib import nullcontext
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    evidence = {"diagnostic_only": True, "arm": args.arm, "deadline_ms": 250,
        "extra_dom_reads": 0, "script_injection": False, "instrumentation_overhead_calibrated": False,
        "platform": platform.platform(), "vsix_sha256": sha256(args.vsix.read_bytes()).hexdigest(),
        "calls": rows}
    original_argv = sys.argv
    sys.argv = [str(SCRIPTS / "check_usage_breakdown_webview.py"), "--code", str(args.code),
        "--vsix", str(args.vsix), "--qualification-input", str(args.qualification_input),
        "--output", str(args.output)]
    try:
        with protocol_trace(NativeSpeedTarget, rows) if args.arm == "traced" else nullcontext():
            runpy.run_path(sys.argv[0], run_name="__main__")
        evidence["replay_passed"] = True
    except BaseException as error:
        evidence["replay_passed"] = False
        evidence["failure"] = type(error).__name__ + ": " + str(error)[:4000]
        raise
    finally:
        sys.argv = original_argv
        (args.output / "protocol-timings.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
