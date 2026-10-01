"""Bounded live-only replay and separately labeled reconstructed sensitivity."""
import argparse
import json
import math
import time
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from evidence import current_suffix
from measures import DAILY, RECENT, eligible, forecast, interval_rate, net_rate, paired, rates


def distribution(values):
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    def percentile(fraction):
        return ordered[min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)]
    return {"n": len(values), "median": median(ordered), "p90": percentile(.9), "max": ordered[-1]}


def live_cycles(live):
    cycles = []
    for index, point in enumerate(live):
        evidence = current_suffix(live[:index + 1], point)
        previous_time = live[index - 1]["seconds"] if index else None
        retained = any(previous["seconds"] == previous_time for previous in evidence.points)
        reason = "observation-conflict" if evidence.conflict else evidence.boundary if index and not retained else ""
        if not cycles or reason:
            if cycles:
                cycles[-1]["closure"] = reason
                cycles[-1]["boundary_time"] = point["seconds"]
            cycles.append({"points": [], "closure": "ongoing"})
        cycles[-1]["points"].append(point)
    mapping = {point["read_id"]: index for index, cycle in enumerate(cycles) for point in cycle["points"]}
    return cycles, mapping


def future_target(live, index, hours, cycle_map):
    anchor = live[index]
    target = anchor["seconds"] + hours * 3600
    stamps = [point["seconds"] for point in live]
    future_index = bisect_left(stamps, target, lo=index + 1)
    if future_index == len(live):
        return None
    point = live[future_index]
    target_end = bisect_right(stamps, point["seconds"])
    if current_suffix(live[:target_end], point).conflict:
        return None
    # Score at a real observation, never at an interpolated target time.
    if point["seconds"] - target > 900 or cycle_map[point["read_id"]] != cycle_map[anchor["read_id"]]:
        return None
    segment = live[index:future_index + 1]
    if any(b["seconds"] - a["seconds"] > 1800 for a, b in zip(segment, segment[1:])):
        return None
    return point


def proxy_error(row, value, target, *, capped=False):
    projected = row["used"] + value["rate"] * (target["seconds"] - row["seconds"]) / 3600
    return (min(100, max(0, projected)) if capped else projected) - target["used"]


def summarize_rows(rows):
    output = {}
    for horizon in ("recent", "daily"):
        methods = ["level-median", "level-paired", "net"]
        if horizon == "daily":
            methods.insert(0, "interval-weighted")
        horizon_rows = [row[horizon] for row in rows]
        output[horizon] = {
            "opportunities": len(rows),
            "evidence_reasons": dict(Counter(row["reason"] for row in horizon_rows)),
            "methods": {},
        }
        for method in methods:
            chosen = [(row, row[horizon]["forecasts"][method]) for row in rows
                      if method in row[horizon].get("forecasts", {})]
            errors = defaultdict(list)
            stability, flips, pairs, availability_changes = [], 0, 0, 0
            previous = None
            previous_available = None
            for row in rows:
                value = row[horizon].get("forecasts", {}).get(method)
                if previous_available is not None:
                    availability_changes += (value is not None) != previous_available
                previous_available = value is not None
                if value is None:
                    previous = None
                    continue
                for hours, target in row["targets"].items():
                    errors[hours].append(proxy_error(row, value, target))
                if previous and previous[0]["cycle"] == row["cycle"] and row["seconds"] - previous[0]["seconds"] <= 1800:
                    stability.append(abs(value["exhaustion"] - previous[1]["exhaustion"]) / 3600)
                    flips += value["outcome"] != previous[1]["outcome"]
                    pairs += 1
                previous = row, value
            by_cycle = {}
            for cycle in sorted({row["cycle"] for row in rows if row["cycle"] is not None}):
                group = [row for row in rows if row["cycle"] == cycle]
                available = [row for row in group if method in row[horizon].get("forecasts", {})]
                by_cycle[cycle] = {"opportunities": len(group), "available": len(available)}
            output[horizon]["methods"][method] = {
                "available": len(chosen), "available_percent": 100 * len(chosen) / len(rows) if rows else 0,
                "outcomes": dict(Counter(value["outcome"] for _, value in chosen)),
                "actual_span_hours": distribution([row[horizon]["span"] for row, _ in chosen]),
                "proxy_errors_pp": {hours: {
                    "signed_median": median(values), "absolute": distribution([abs(value) for value in values]),
                    "underpredicted": distribution([-value for value in values if value < 0]),
                    "overpredicted": distribution([value for value in values if value > 0]),
                } for hours, values in errors.items()},
                "absolute_eta_change_hours": distribution(stability),
                "outcome_flips": flips, "adjacent_pairs": pairs, "by_cycle": by_cycle,
                "availability_changes": availability_changes,
            }
        # Matched origins prevent differing abstention from improving a score.
        matched = [row for row in rows if methods and all(method in row[horizon].get("forecasts", {}) for method in methods)]
        output[horizon]["matched_proxy_errors_pp"] = {}
        output[horizon]["matched_capped_meter_errors_pp"] = {}
        for hours in ("1", "3"):
            group = [row for row in matched if hours in row["targets"]]
            output[horizon]["matched_proxy_errors_pp"][hours] = {
                method: distribution([
                    abs(proxy_error(row, row[horizon]["forecasts"][method], row["targets"][hours]))
                    for row in group
                ]) for method in methods
            }
            output[horizon]["matched_capped_meter_errors_pp"][hours] = {
                method: distribution([
                    abs(proxy_error(row, row[horizon]["forecasts"][method], row["targets"][hours], capped=True))
                    for row in group
                ]) for method in methods
            }
    return output


def evaluate(snapshot, *, mixed=False):
    started = time.perf_counter()
    live = sorted(snapshot["live"], key=lambda point: point["read_id"])
    cycles, cycle_map = live_cycles(live)
    by_id = {point["read_id"]: (index, point) for index, point in enumerate(live)}
    task_points = sorted(snapshot["points"], key=lambda point: point["seconds"]) if mixed else []
    task_stamps = [point["seconds"] for point in task_points]
    rows, fit_times, suffix_times = [], [], []
    for read in snapshot["reads"]:
        row = {"read_id": read["read_id"], "seconds": datetime.fromisoformat(read["timestamp"]).timestamp(),
               "cycle": None, "targets": {}}
        if read["read_id"] not in by_id:
            row.update({horizon: {"reason": "no-live-bucket", "forecasts": {}} for horizon in ("recent", "daily")})
            rows.append(row)
            continue
        index, anchor = by_id[read["read_id"]]
        row.update({"cycle": cycle_map[anchor["read_id"]], "used": anchor["used"], "reset": anchor["reset"],
                    "targets": {str(hours): target for hours in (1, 3) if (target := future_target(live, index, hours, cycle_map))}})
        prefix = live[:index + 1] + task_points[:bisect_right(task_stamps, anchor["seconds"])]
        suffix_started = time.perf_counter()
        evidence = current_suffix(prefix, anchor)
        suffix_times.append((time.perf_counter() - suffix_started) * 1000)
        row["boundary"] = evidence.boundary
        row["corrections"] = evidence.corrections
        row["suffix_start"] = evidence.points[0]["seconds"] if evidence.points else None
        for horizon, gates in (("recent", RECENT), ("daily", DAILY)):
            chosen, reason = eligible(evidence.points, anchor, gates)
            if evidence.conflict:
                reason = "anchor-conflict"
            fit = {"reason": reason, "forecasts": {}, "span": 0,
                   "n": len(chosen), "movement": chosen[-1]["used"] - chosen[0]["used"] if chosen else 0}
            if chosen:
                fit["span"] = (chosen[-1]["seconds"] - chosen[0]["seconds"]) / 3600
            if reason == "available":
                fitting = time.perf_counter()
                fit["forecasts"] = {method: value for method, rate in rates(chosen, gates).items()
                                    if (value := forecast(anchor, rate)) is not None}
                fit_times.append((time.perf_counter() - fitting) * 1000)
            row[horizon] = fit
        rows.append(row)
    holdout_start = 2
    available_rows = [row for row in rows if row["cycle"] is not None]
    result = {
        "source_mode": "reconstructed-retrospective" if mixed else "strict-live-only",
        "summary": summarize_rows(rows),
        "successful_origins": summarize_rows(available_rows),
        "early_cycles": summarize_rows([row for row in available_rows if row["cycle"] < holdout_start]),
        "later_cycles": summarize_rows([row for row in available_rows if row["cycle"] >= holdout_start]),
        "low_remaining": summarize_rows([row for row in available_rows if row["used"] >= 90]),
        "ongoing_cycle": summarize_rows([row for row in available_rows if row["cycle"] == len(cycles) - 1]),
        "timing_ms": {"all_method_fits": distribution(fit_times), "prefix_continuity": distribution(suffix_times)},
        "elapsed_seconds": time.perf_counter() - started,
        "cycles": [{"start": cycle["points"][0]["timestamp"], "end": cycle["points"][-1]["timestamp"],
                    "n": len(cycle["points"]), "closure": cycle["closure"],
                    "observed_100": sum(point["used"] >= 100 for point in cycle["points"]),
                    "intervened_before_advertised_reset": (cycle["points"][-1]["reset"] is not None
                         and cycle.get("boundary_time", float("inf")) < cycle["points"][-1]["reset"])}
                   for cycle in cycles],
        "latest": rows[-1] if rows else None,
        "latest_successful_origin": next((row for row in reversed(rows) if row["cycle"] is not None), None),
        "rows": rows,
    }
    return result


def sensitivity(snapshot):
    live = sorted(snapshot["live"], key=lambda point: point["read_id"])
    _, cycle_map = live_cycles(live)
    options = {
        "recent-movement-1": replace(RECENT, movement=1),
        "recent-movement-2": RECENT,
        "recent-movement-3": replace(RECENT, movement=3),
        "recent-lookback-30m": replace(RECENT, lookback_hours=.5, minimum_span_hours=.25),
        "recent-lookback-90m": replace(RECENT, lookback_hours=1.5),
        "daily-movement-1": replace(DAILY, movement=1),
        "daily-movement-2": DAILY,
        "daily-movement-3": replace(DAILY, movement=3),
    }
    counts = {name: Counter() for name in options}
    decay = {hours: [] for hours in (3, 6, 12)}
    proxies = {name: defaultdict(list) for name in options}
    matched_movement = {name: defaultdict(list) for name in ("movement-1-only", "movement-2-or-more")}
    decay_proxies = {hours: defaultdict(list) for hours in decay}
    for index, anchor in enumerate(live):
        evidence = current_suffix(live[:index + 1], anchor)
        targets = {hours: target for hours in (1, 3) if (target := future_target(live, index, hours, cycle_map))}
        for name, gates in options.items():
            selected, reason = eligible(evidence.points, anchor, gates)
            counts[name][reason] += 1
            if reason == "available":
                rate = net_rate(paired(selected)) if name.startswith("recent") else interval_rate(paired(selected), 6)
                value = forecast(anchor, rate)
                if value:
                    for hours, target in targets.items():
                        error = abs(proxy_error(anchor, value, target))
                        proxies[name][hours].append(error)
                        if name == "recent-movement-1":
                            group = "movement-2-or-more" if selected[-1]["used"] - selected[0]["used"] >= 2 else "movement-1-only"
                            matched_movement[group][hours].append(error)
        selected, reason = eligible(evidence.points, anchor, DAILY)
        if reason == "available":
            for half_life in decay:
                value = forecast(anchor, interval_rate(paired(selected), half_life))
                if value:
                    decay[half_life].append(value["rate"])
                    for hours, target in targets.items():
                        decay_proxies[half_life][hours].append(abs(proxy_error(anchor, value, target)))
    return {"gates": {name: dict(counter) for name, counter in counts.items()},
            "proxy_errors_pp": {name: {hours: distribution(values) for hours, values in errors.items()}
                                for name, errors in proxies.items()},
            "recent_movement_strata_pp": {name: {hours: distribution(values) for hours, values in errors.items()}
                                         for name, errors in matched_movement.items()},
            "daily_half_life_rate_pp_hour": {hours: distribution(values) for hours, values in decay.items()},
            "daily_half_life_proxy_errors_pp": {name: {hours: distribution(values) for hours, values in errors.items()}
                                               for name, errors in decay_proxies.items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text())
    live_result = evaluate(snapshot)
    print("Strict live replay complete", flush=True)
    mixed_result = evaluate(snapshot, mixed=True)
    print("Reconstructed sensitivity complete", flush=True)
    output = {"snapshot": snapshot["meta"], "live": live_result, "mixed": mixed_result,
              "sensitivity": sensitivity(snapshot), "generated_at": datetime.now(UTC).isoformat()}
    args.output.write_text(json.dumps(output, indent=2))
    args.output.chmod(0o600)
    print(json.dumps({"cycles": live_result["cycles"], "latest": live_result["latest"],
                      "sensitivity": output["sensitivity"]}, indent=2))


if __name__ == "__main__":
    main()
