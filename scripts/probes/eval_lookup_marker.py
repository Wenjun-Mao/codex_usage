"""Nonqualifying, per-document public eval lookup marker and descriptor control."""
from contextlib import contextmanager
import json
import math
from uuid import uuid4


INSTALL = """config => {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'eval');
    if (!descriptor || !descriptor.configurable || !descriptor.writable
        || typeof descriptor.value !== 'function'
        || !Function.prototype.toString.call(descriptor.value).includes('[native code]'))
        throw new Error('Expected native, writable public eval data descriptor');
    if (Object.hasOwn(globalThis, '__codex_eval_lookup_marker'))
        throw new Error('Unexpected existing eval marker');
    const state = {mode:config.mode, token:config.token, original:descriptor,
        origin:performance.timeOrigin, performance_ref:performance, now_ref:performance.now,
        records:[], sequence:0, dropped:0, assignments:0};
    Object.defineProperty(globalThis, '__codex_eval_lookup_marker',
        {value:state, configurable:true});
    state.getter = () => {
        const sequence = ++state.sequence;
        state.records.push({sequence, entry_ms:state.performance_ref.now(), time_origin:state.origin,
            clock_domain:state.token});
        if (state.records.length > 64) { state.records.shift(); ++state.dropped; }
        return descriptor.value;
    };
    state.setter = () => {
        ++state.assignments;
        throw new Error('Unexpected eval assignment during diagnostic');
    };
    if (config.mode === 'clock') {
        Object.defineProperty(globalThis, 'eval', {configurable:descriptor.configurable,
            enumerable:descriptor.enumerable, get:state.getter, set:state.setter});
    } else if (config.mode === 'descriptor') {
        Object.defineProperty(globalThis, 'eval', descriptor);
    } else {
        throw new Error('Unsupported eval marker mode');
    }
    return {mode:state.mode, token:state.token, time_origin:state.origin, clock_domain:state.token};
}"""

SNAPSHOT = """token => {
    const state = globalThis.__codex_eval_lookup_marker;
    if (!state || state.token !== token || state.performance_ref !== performance
        || state.now_ref !== performance.now)
        throw new Error('Eval marker document or realm changed');
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'eval');
    const common = descriptor && descriptor.configurable === state.original.configurable
        && descriptor.enumerable === state.original.enumerable;
    const intact = common && (state.mode === 'clock'
        ? descriptor.get === state.getter && descriptor.set === state.setter
        : descriptor.value === state.original.value && descriptor.writable === state.original.writable);
    if (!intact || state.assignments)
        throw new Error('Eval descriptor changed during diagnostic');
    return {mode:state.mode, token:state.token, time_origin:state.origin,
        clock_domain:state.token, epoch_origin_is_anchor:true,
        sequence:state.sequence, dropped:state.dropped, assignments:state.assignments,
        latest:state.records.length ? state.records[state.records.length - 1] : null};
}"""

RESTORE = """token => {
    const state = globalThis.__codex_eval_lookup_marker;
    if (!state || state.token !== token || state.performance_ref !== performance
        || state.now_ref !== performance.now)
        throw new Error('Eval cleanup document or realm changed');
    let snapshot = null;
    let integrity_error = false;
    try { snapshot = (SNAPSHOT)(token); } catch { integrity_error = true; }
    const records = state.records.slice();
    const current = Object.getOwnPropertyDescriptor(globalThis, 'eval');
    const owned = current && (state.mode === 'clock'
        ? current.get === state.getter && current.set === state.setter
        : current.value === state.original.value && current.writable === state.original.writable);
    if (owned) Object.defineProperty(globalThis, 'eval', state.original);
    const restored = Object.getOwnPropertyDescriptor(globalThis, 'eval');
    const descriptor_equal = !!restored && restored.value === state.original.value
        && restored.writable === state.original.writable
        && restored.configurable === state.original.configurable
        && restored.enumerable === state.original.enumerable;
    delete globalThis.__codex_eval_lookup_marker;
    return {snapshot, records, descriptor_equal, integrity_error, restoration_attempted:!!owned};
}""".replace("SNAPSHOT", SNAPSHOT)


class EvalLookupMarker:
    def __init__(self, mode, documents):
        if mode not in ("descriptor", "clock"):
            raise ValueError("Unsupported public eval marker mode")
        self.mode, self.documents, self.active = mode, documents, {}

    @contextmanager
    def document(self, page, case):
        if case["engine"] != "webkit":
            yield
            return
        token = uuid4().hex
        record = {"case": case, "mode": self.mode, "token": token,
            "page_url": page.url, "qualified": False}
        self.documents.append(record)
        primary = None
        installation_attempted = False
        try:
            installation_attempted = True
            setup = page.evaluate(INSTALL, {"mode": self.mode, "token": token})
            if (setup.get("token") != token or setup.get("mode") != self.mode
                or setup.get("clock_domain") != token or not _finite_ms(setup.get("time_origin"))):
                raise RuntimeError("Eval marker installation identity mismatch")
            record["installation"] = setup
            self.active[id(page)] = {"token": token, "origin": setup["time_origin"],
                "url": page.url, "frame": page.main_frame, "last_sequence": 0}
            yield
        except BaseException as error:
            primary = error
            record["failure"] = type(error).__name__
            raise
        finally:
            try:
                if installation_attempted:
                    result = page.evaluate(RESTORE, token)
                    record["readback"] = result
                    if not result.get("descriptor_equal") or result.get("integrity_error"):
                        raise RuntimeError("Eval descriptor restoration mismatch")
            except BaseException as error:
                record["cleanup_failure"] = type(error).__name__
                if primary is None:
                    raise
                primary.add_note("Eval marker cleanup failed: " + type(error).__name__)
            finally:
                self.active.pop(id(page), None)

    def body_snapshot(self, page):
        state = self.active.get(id(page))
        if state is None:
            return "null"
        if page.main_frame is not state["frame"] or page.url != state["url"]:
            raise RuntimeError("Eval marker page/frame changed")
        return "(" + SNAPSHOT + ")(" + json.dumps(state["token"]) + ")"

    def validate(self, page, snapshot, body_entry, raw_epoch_origin):
        state = self.active.get(id(page))
        if state is None:
            if snapshot is not None:
                raise RuntimeError("Unexpected eval marker outside its bound document")
            return
        if (not isinstance(snapshot, dict) or snapshot.get("token") != state["token"]
            or snapshot.get("mode") != self.mode or snapshot.get("time_origin") != state["origin"]
            or snapshot.get("clock_domain") != state["token"] or snapshot.get("assignments") != 0
            or not _finite_ms(body_entry)):
            raise RuntimeError("Eval marker document/realm mismatch")
        dropped = snapshot.get("dropped")
        sequence = snapshot.get("sequence")
        if (not isinstance(dropped, int) or isinstance(dropped, bool) or dropped < 0
            or not isinstance(sequence, int) or isinstance(sequence, bool) or dropped > sequence):
            raise RuntimeError("Eval marker overflow/sequence metadata is unavailable")
        if self.mode == "clock":
            mark = snapshot.get("latest")
            if (not isinstance(mark, dict) or not isinstance(sequence, int)
                or sequence <= state["last_sequence"] or mark.get("sequence") != sequence
                or mark.get("time_origin") != state["origin"] or mark.get("clock_domain") != state["token"]
                or not _finite_ms(mark.get("entry_ms")) or mark["entry_ms"] > body_entry):
                raise RuntimeError("Missing, overwritten or unattributable eval lookup mark")
            state["last_sequence"] = sequence
        elif snapshot.get("latest") is not None or sequence != 0 or dropped != 0:
            raise RuntimeError("Descriptor control unexpectedly produced an accessor mark")


def _finite_ms(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
