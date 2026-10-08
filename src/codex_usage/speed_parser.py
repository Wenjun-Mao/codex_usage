"""Conservative ordered response pairing; checkpoints contain no generated content."""
from copy import deepcopy

from codex_usage.models import UsageRecord
from codex_usage.speed_models import METRIC_VERSION, MIN_ITEM_MS, SpeedFact, counts, milliseconds

MAX_ITEMS = 128


def identity(value):
    return value if isinstance(value, str) and len(value) <= 256 else ""


class SpeedParser:
    def __init__(self, state: dict | None = None):
        self.state = deepcopy(state) if state and state.get("version") == METRIC_VERSION else {}
        self.facts: list[SpeedFact] = []
        self.tools: list[tuple[float, float]] = []
        self.matched = None

    def dirty(self, reason: str = "incomplete_response_boundary") -> None:
        self.state["reason"] = reason

    def observe_prefix(self, prefix, model, turn):
        from codex_usage.speed_projection import project_prefix
        projected = project_prefix(prefix)
        payload = projected.get("payload", {})
        if projected.get("type") != "response_item" or not payload.get("type"):
            self.dirty()
            return
        self.observe(projected, model, turn)

    def observe(self, obj: dict, model: str, turn: str) -> None:
        self.matched = None
        outer = obj.get("type")
        if outer == "session_meta":
            # Fork headers may be newer than their inherited response history.
            self.state = {}
            return
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        at = milliseconds(obj.get("timestamp"))
        previous_at = self.state.get("last_at")
        reversed_time = at is not None and previous_at is not None and at < previous_at
        if reversed_time:
            self.dirty("reversed_timestamp_order")
        if at is not None:
            self.state["last_at"] = at
        if outer == "turn_context" or kind == "task_started":
            self.state = {
                "version": METRIC_VERSION, "safe": not reversed_time,
                "turn": identity(payload.get("turn_id") or turn),
                "model": identity(payload.get("model") or model), "items": [], "last_at": at,
            }
            if reversed_time:
                self.dirty("reversed_timestamp_order")
            return
        if kind in {"task_complete", "turn_aborted", "task_aborted"}:
            self.state = {}
            return
        if kind == "item_completed":
            item = payload.get("item") or {}
            item_type = item.get("type") if isinstance(item, dict) else None
            start = milliseconds(payload.get("started_at_ms"))
            end = milliseconds(payload.get("completed_at_ms"))
            if item_type in {"Reasoning", "AgentMessage"}:
                if self.state.get("pending") is not None:
                    self.dirty("generation_after_response_record")
                items = self.state.setdefault("items", [])
                if len(items) >= MAX_ITEMS:
                    self.dirty("timing_state_limit")
                else:
                    items.append([identity(payload.get("turn_id")), start, end, item_type, identity(item.get("id"))])
            elif start is not None and end is not None and end >= start:
                self.tools.append((start, end))
            else:
                self.tools.append((-1, -1))
                self.dirty("missing_tool_interval")
        if outer == "response_item":
            generated = kind in {"reasoning", "function_call", "custom_tool_call"} or (
                kind == "message" and payload.get("role") == "assistant"
            )
            if generated:
                meta = payload.get("internal_chat_message_metadata_passthrough") or {}
                if not isinstance(meta, dict):
                    meta = {}
                    self.dirty("invalid_output_metadata")
                if at is None or (meta.get("turn_id") and meta["turn_id"] != self.state.get("turn")):
                    self.dirty("mixed_or_missing_output_timestamp")
                else:
                    self.state["output_end"] = max(at, self.state.get("output_end", at))
                    self.state["output_start"] = min(at, self.state.get("output_start", at))
                if self.state.get("pending") is not None:
                    self.dirty("generation_after_response_record")
            elif kind in {"function_call_output", "custom_tool_call_output"} and at is not None:
                self.tools.append((at, at))
            elif kind in {"function_call_output", "custom_tool_call_output"}:
                self.tools.append((-1, -1))
        if outer == "token_usage_record":
            if self.state.get("pending") is not None:
                self.dirty("ambiguous_response_records")
            response_id = payload.get("response_id")
            self.state["pending"] = {
                "id": response_id if isinstance(response_id, str) and len(response_id) <= 256 else "",
                "turn": identity(payload.get("turn_id")), "model": identity(payload.get("model")),
                "usage": counts(payload.get("usage")), "at": at,
            }
        if kind == "token_count":
            self.matched = deepcopy(self.state)
            info = payload.get("info") or {}
            self.matched["last"] = counts(info.get("last_token_usage"))
            self.matched["count_at"] = at
            self.state = {"version": METRIC_VERSION, "safe": True, "turn": identity(turn),
                          "model": identity(model), "items": [], "last_at": at}

    def finish(self, record: UsageRecord, record_index: int, cli_version: str) -> None:
        state = self.matched or {}
        pending = state.get("pending") or {}
        usage = counts(record.usage.to_dict())
        items = state.get("items", [])
        valid = [i for i in items if i[1] is not None and i[2] is not None]
        start = min((i[1] for i in valid), default=0)
        end = max([i[2] for i in valid] + [state.get("output_end", 0)])
        floor = min((i[2] - i[1] for i in valid), default=0)
        reason = state.get("reason", "")
        if not reason:
            reason = self._reason(state, pending, record, usage, items, start, end, floor)
        self.facts.append(SpeedFact(
            record_index, pending.get("id", ""), record.timestamp.isoformat(),
            record.session_id, record.turn_id, record.model, record.effort, cli_version,
            usage, start, end, floor, len(items), reason,
        ))

    @staticmethod
    def _reason(state, pending, record, usage, items, start, end, floor) -> str:
        if not state.get("safe") or not pending:
            return "incomplete_response_boundary"
        if not pending.get("id"):
            return "missing_response_id"
        if tuple(pending.get("usage") or ()) != usage or tuple(state.get("last") or ()) != usage:
            return "token_fields_mismatch"
        if usage[4] > usage[3] or usage[5] != usage[0] + usage[3]:
            return "invalid_usage_relationship"
        if not record.turn_id or pending.get("turn") != record.turn_id or state.get("turn") != record.turn_id:
            return "turn_mismatch"
        if state.get("model") != record.model or record.model == "unknown" or (pending.get("model") and pending["model"] != record.model):
            return "model_mismatch"
        if not items or any(i[0] != record.turn_id or i[1] is None or i[2] is None for i in items):
            return "missing_or_mixed_timed_items"
        if floor < 0:
            return "negative_item_duration"
        if floor == 0:
            return "collapsed_item_duration"
        if floor < MIN_ITEM_MS:
            return "sub_resolution_item_duration"
        identities = [i[4] for i in items if i[4]]
        if len(identities) != len(set(identities)):
            return "duplicate_item_identity"
        ordered = sorted(items, key=lambda i: i[1])
        if any(a[2] > b[1] for a, b in zip(ordered, ordered[1:])):
            return "overlapping_model_intervals"
        if usage[4] and not any(i[3] == "Reasoning" for i in items):
            return "missing_reasoning_interval"
        received, counted = pending.get("at"), state.get("count_at")
        if received is None or counted is None or not (start < end <= received <= counted):
            return "impossible_timestamp_order"
        if state.get("output_start", start) < start:
            return "impossible_timestamp_order"
        return "" if usage[3] else "no_output"
