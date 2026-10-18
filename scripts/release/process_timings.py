"""Wall and runner intervals kept distinct for observed workflow progress."""
from datetime import datetime

from .policy import require


def elapsed(start, end):
    result = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    require(result >= 0, "Reversed workflow timestamps")
    return result


def workflow_timing(run, jobs):
    rows = []
    for job in jobs:
        if job.get("conclusion") == "skipped":
            continue
        require(job.get("status") == "completed", "Incomplete workflow timing")
        rows.append({"job": job["name"], "eligibility_wait_seconds": elapsed(job["created_at"], job["started_at"]),
            "execution_seconds": elapsed(job["started_at"], job["completed_at"]),
            "steps": [{"name": s["name"], "seconds": elapsed(s["started_at"], s["completed_at"])}
                for s in job["steps"] if s.get("conclusion") != "skipped"]})
    return {"run": run["id"], "attempt": run["run_attempt"],
        "wall_seconds": elapsed(run["created_at"], run["updated_at"]),
        "concurrent_runner_seconds": sum(r["execution_seconds"] for r in rows), "jobs": rows}


def comparison(timings):
    lines = ["| Workflow | Observed Wall | Baseline 2.12.5 |", "| --- | ---: | ---: |"]
    for name, data in timings.items():
        baseline = "739s (two slots)" if name == "qualification" else "168s" if name == "promotion" else "29s"
        lines.append(f"| {name} | {data['wall_seconds']:.1f}s | {baseline} |")
    return "\n".join(lines) + "\n"
