"""Held diagnostic sampler; attachment requires a reviewed public ownership contract."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
from time import monotonic, sleep

from probes.browser_provenance import file_digest
from probes.darwin_process_identity import process_identity

XPC_EXECUTABLES = {"com.apple.WebKit." + kind + ".xpc": "com.apple.WebKit." + kind + ".Development"
    for kind in ("WebContent", "Networking", "GPU")}


def require_ephemeral_host(env=os.environ):
    if (platform.system() != "Darwin" or env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != "Wenjun-Mao/codex_usage"
        or env.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or env.get("GITHUB_JOB") != "diagnostic" or env.get("GITHUB_REF") != "refs/heads/main"):
        raise ValueError("Process sampling is restricted to the ephemeral main diagnostic job")


def require_sampling_contract():
    raise RuntimeError("Process sampling unavailable: public process identity and fixture association are not established")


def process_table(text):
    rows = {}
    for line in text.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            rows[int(fields[0])] = {"parent": int(fields[1]), "executable": fields[2]}
    return rows


def descendants(rows, owner):
    found = {owner}
    while True:
        children = {pid for pid, row in rows.items() if row["parent"] in found}
        if children <= found:
            return found - {owner}
        found |= children


def selected_processes(rows, owner, driver):
    owned = descendants(rows, owner)
    roots = {root for pid, row in rows.items() if pid in owned
        for root in Path(row["executable"]).resolve().parents if root.name.startswith("webkit-")}
    webkit = {pid: row for pid, row in rows.items()
        if any(Path(row["executable"]).resolve().is_relative_to(root) for root in roots)
        and pid in owned}
    if not webkit:
        return {}
    # Bundle affinity alone cannot associate a reparented XPC service with this run.
    return {**webkit, **{pid: row for pid, row in rows.items()
        if pid in owned and row["executable"] == str(driver)}}


def is_xpc(path):
    return len(path.parts) >= 4 and path.parts[-3:-1] == ("Contents", "MacOS") and (
        XPC_EXECUTABLES.get(path.parts[-4]) == path.name)


def attachment_identity(pid, row):
    first = process_identity(pid)
    if first is None or first["parent"] != row["parent"]:
        return None
    executable = Path(first["executable"]).resolve()
    if executable != Path(row["executable"]).resolve() or not executable.is_file():
        return None
    digest = file_digest(executable)
    if process_identity(pid) != first or file_digest(executable) != digest:
        return None
    return {**first, "executable_sha256": digest}


def finish_samples(jobs):
    codes, deadline = {}, monotonic() + 10
    for pid, job in jobs.items():
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        try:
            codes[pid] = job.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            break
    for pid, job in jobs.items():
        if pid not in codes and job.poll() is None:
            job.kill()
    deadline = monotonic() + 2
    for pid, job in jobs.items():
        if pid not in codes:
            codes[pid] = job.wait(timeout=max(.001, deadline - monotonic()))
    return codes


def monitor(output, owner, driver):
    require_ephemeral_host()
    require_sampling_contract()
    output.mkdir(parents=True, exist_ok=True)
    stopped, jobs, records = [False], {}, {}
    signal.signal(signal.SIGTERM, lambda *_: stopped.__setitem__(0, True))
    started = monotonic()
    try:
        while not stopped[0] and monotonic() - started < 90:
            raw = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,ppid=,comm="],
                capture_output=True, text=True, check=True, timeout=2).stdout
            rows = process_table(raw)
            if owner not in rows:
                break
            for pid, row in selected_processes(rows, owner, driver).items():
                if pid in jobs:
                    continue
                record = attachment_identity(pid, row)
                if record is None:
                    continue
                record["started_after_seconds"] = monotonic() - started
                jobs[pid] = subprocess.Popen(["/usr/bin/sample", str(pid), "8", "2", "-mayDie",
                    "-fullPaths", "-file", str(output / f"process-{pid}.txt")],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                records[str(pid)] = record
            sleep(.2)
    finally:
        for pid, code in finish_samples(jobs).items():
            records[str(pid)]["sample_exit_code"] = code
            path = output / f"process-{pid}.txt"
            records[str(pid)]["sample_available"] = code == 0 and path.is_file() and path.stat().st_size > 0
        (output / "processes.json").write_text(json.dumps({"diagnostic_only": True,
            "sampling_overhead_uncalibrated": True, "sample_duration_seconds": 8,
            "sample_interval_ms": 2, "owner": owner, "processes": records}, indent=2) + "\n")


@contextmanager
def sampling(output, enabled):
    status = {"enabled": enabled}
    if not enabled:
        yield status
        return
    require_ephemeral_host()
    require_sampling_contract()
    import playwright
    driver = Path(playwright.__file__).parent / "driver/node"
    process = subprocess.Popen([sys.executable, "-m", "probes.webkit_process_sample",
        "--output", str(output), "--owner", str(os.getpid()),
        "--driver", str(driver)],
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, start_new_session=True)
    failed = False
    try:
        yield status
    except BaseException:
        failed = True
        raise
    finally:
        try:
            if process.poll() is None:
                process.terminate()
            try:
                code = process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait(timeout=2)
            status.update(exit_code=code, original_observation_failed=failed)
            output.mkdir(parents=True, exist_ok=True)
            (output / "sampler-status.json").write_text(json.dumps(status) + "\n")
            if code:
                raise RuntimeError(f"Diagnostic sampler failed: {code}")
        except Exception as error:
            status["cleanup_error"] = str(error)[:1000]
            try:
                os.killpg(process.pid, signal.SIGKILL)
                if process.poll() is None:
                    process.wait(timeout=2)
            except ProcessLookupError:
                pass
            except Exception as forced_error:
                status["forced_cleanup_error"] = str(forced_error)[:1000]
            if not failed:
                raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--owner", type=int, required=True)
    parser.add_argument("--driver", type=Path, required=True)
    args = parser.parse_args()
    monitor(args.output, args.owner, args.driver)
