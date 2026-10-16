"""Mandatory collector lifecycle/parallel proof bound to the shipped executable."""
import json

from .policy import digest, positive, require


def validate_collector_proof(files, package):
    require("collector-parallel.json" in files, "Missing collector parallel proof")
    proof = json.loads(files["collector-parallel.json"])
    require(proof.get("contract") == "collector-parallel-http-v1"
            and proof.get("oracle_equal") is True, "Invalid collector oracle contract")
    require(digest(proof.get("collector_sha256")) == package["collector_sha256"],
            "Collector proof/executable mismatch")
    cold = proof.get("cold", {})
    target = package["target"]
    require((cold.get("sys_platform"), str(cold.get("machine")).lower()) in
            ({("darwin", "arm64")} if target == "darwin-arm64" else
             {("win32", "amd64"), ("win32", "x86_64")}), "Collector proof target mismatch")
    require(type(cold.get("version")) is int and cold["version"] == 1,
            "Unknown capture audit version")
    positive(cold.get("capture_run_id"))
    require(cold.get("coverage_complete") is True and cold.get("oracle_equal") is True
            and type(cold.get("source_bytes_read")) is int and cold["source_bytes_read"] > 0
            and type(cold.get("corpus_bytes")) is int and type(cold.get("parsed_bytes")) is int
            and cold["source_bytes_read"] >= cold["parsed_bytes"] == cold["corpus_bytes"] > 0
            and type(cold.get("completed_events")) is int
            and cold["completed_events"] == 12000
            and type(cold.get("pending_files")) is int and cold["pending_files"] == 0
            and type(cold.get("pending_bytes")) is int and cold["pending_bytes"] == 0,
            "Collector cold capture did not complete")
    cleanup = proof.get("cleanup")
    require(isinstance(cleanup, dict) and set(cleanup) == {"forced_timeout", "collector_observed_alive",
            "collector_observed_exited"} and all(value is True for value in cleanup.values()),
            "Missing observed timeout cleanup")
    parent = positive(cold.get("parent_pid"))
    run = cold.get("usage_run", {})
    pids = run.get("worker_pids", [])
    require(isinstance(pids, list) and len(pids) >= 2 and
            all(type(pid) is int and pid > 0 for pid in pids) and
            len(set(pids)) == len(pids) and parent not in pids, "Collector workers not independent")
    require(type(run.get("resolved_worker_count")) is int and
            2 <= run["resolved_worker_count"] <= 4 and
            type(run.get("max_concurrency")) is int and
            2 <= run["max_concurrency"] <= run["resolved_worker_count"] and
            len(pids) <= run["resolved_worker_count"], "Collector workers did not overlap")
    require(run.get("used_serial_fallback") is False and run.get("infrastructure_error") == ""
            and type(run.get("file_error_count")) is int and run["file_error_count"] == 0
            and type(run.get("span_count")) is int and run["span_count"] == 12,
            "Collector worker failure or incomplete capture")
    require(type(proof.get("unchanged_source_bytes")) is int and proof["unchanged_source_bytes"] == 0
            and type(proof.get("append_events")) is int and proof["append_events"] == 12,
            "Collector incremental work proof missing")
    return proof
