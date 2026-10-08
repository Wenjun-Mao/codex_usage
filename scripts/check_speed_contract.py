"""Replay content-free frozen metadata through response pairing and thresholds.

Optional private input is never a public fixture. Results contain aggregate
counts and sensitivity only, not source/task/response identities.
This reconstructs rows: it cannot validate original JSON layout, projection,
length-dependent ingestion coverage, or raw-source checkpoint/recovery behavior.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.speed_parser import SpeedParser
from codex_usage.speed_models import TOKEN_FIELDS, milliseconds


def replay(snapshot):
    facts = []
    reasons = Counter()
    for source in snapshot["sources"]:
        events = defaultdict(list)
        for event in source["events"]:
            events[event["timestamp_us"]].append(event)
        parser = SpeedParser()
        model, turn = "unknown", ""
        for row in source["rows"]:
            if row is None:
                parser.dirty()
                continue
            outer, kind = row["outer"], row["kind"]
            payload = {"type": kind}
            if outer == "turn_context":
                model, turn = row.get("model") or model, row.get("turn") or turn
                payload.update(model=model, turn_id=turn)
            elif kind == "item_completed":
                payload.update(turn_id=row.get("turn"), started_at_ms=row.get("start"), completed_at_ms=row.get("end"), item={"type": row.get("item_type")})
            elif outer == "response_item":
                payload.update(role=row.get("role"), internal_chat_message_metadata_passthrough={"turn_id": row.get("turn")})
            elif outer == "token_usage_record":
                payload.update(turn_id=row.get("turn"), response_id=row.get("response_id"), usage=row.get("usage"))
            elif kind == "token_count":
                payload.update(info={"last_token_usage": row.get("last_usage")})
            elif kind in {"task_started", "task_complete"}:
                turn = row.get("turn") or turn
                payload.update(turn_id=turn)
            parser.observe({"type": outer, "timestamp": row.get("at"), "payload": payload}, model, turn)
            if kind != "token_count" or milliseconds(row.get("at")) is None:
                continue
            time_us = int(datetime.fromisoformat(row["at"].replace("Z", "+00:00")).timestamp() * 1_000_000)
            matched = events[time_us]
            if len(matched) != 1:
                reasons["no_unique_trusted_delta"] += 1
                continue
            event = matched[0]
            record = UsageRecord(datetime.fromisoformat(event["timestamp"]), TokenUsage.from_mapping(event),
                "frozen-source", Path("frozen-source"), "root", event["model_key"], event["turn_id"], event.get("effort") or "")
            parser.finish(record, len(facts), "unknown")
        # Late tool evidence applies to every candidate, not just the next one.
        for fact in parser.facts:
            reason = fact.reason
            if not reason and any((a < fact.end_ms and b > fact.start_ms) or (a == b and fact.start_ms < a < fact.end_ms) for a, b in parser.tools):
                reason = "tool_execution_overlap"
            if not reason and fact.turn_id in parser.uncertain_tools:
                reason = "missing_tool_interval"
            facts.append(replace(fact, reason=reason))
    grouped = defaultdict(list)
    for fact in facts:
        grouped[fact.response_id].append(fact)
    unique = []
    for group in grouped.values():
        signatures = {json.dumps({k: v for k, v in f.to_dict().items()
                                 if k not in {"task_id", "record_index", "cli_version", "effort"}}, sort_keys=True) for f in group}
        if not group[0].response_id:
            for fact in group:
                reasons[fact.reason or "missing_response_id"] += 1
            continue
        if len(signatures) != 1:
            reasons["conflicting_response_identity"] += len(group)
        else:
            if group[0].reason:
                reasons[group[0].reason] += len(group)
            else:
                unique.append(group[0])
                reasons["equivalent_duplicate"] += len(group) - 1
    from statistics import median
    sensitivity = {}
    for floor in (10, 50, 100):
        for output in (100, 500, 2000):
            by_model = defaultdict(list)
            for fact in unique:
                if fact.min_item_ms >= floor and fact.usage[TOKEN_FIELDS.index("output_tokens")] >= output:
                    by_model[fact.model].append(fact.usage[3] * 1000 / (fact.end_ms - fact.start_ms))
            sensitivity[f"{floor}ms/{output}tokens"] = {m: {"n": len(s), "median": round(median(s), 3)} for m, s in sorted(by_model.items())}
    return {"evidence_kind": "content_free_pairing_and_threshold_replay_not_ingestion_coverage",
            "accepted": len(unique), "rejections": dict(sorted(reasons.items())), "sensitivity": sensitivity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.private_snapshot.read_bytes()
    results = replay(json.loads(raw))
    results["input_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"accepted": results["accepted"], "input_sha256": results["input_sha256"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
