"""Bounded JSON structural evidence, including fields after large payloads.

Ignored string contents are validated but never accumulated. Checkpoints retain
only bounded header fields and lexer position, not output text or media.
"""
import codecs
import json
import re
from copy import deepcopy
from codex_usage.speed_projection_scalar import begin_scalar, advance_scalar, scalar_complete

FIELDS = {
    (): {"type", "timestamp", "payload"},
    ("payload",): {"type", "role", "turn_id", "internal_chat_message_metadata_passthrough"},
    ("payload", "internal_chat_message_metadata_passthrough"): {"turn_id"},
}
CONTAINERS = {("payload",), ("payload", "internal_chat_message_metadata_passthrough")}
SPECIAL = re.compile(r'["\\\x00-\x1f]')
MAX_DEPTH = 64
MAX_HEADER_BYTES = 2048
DECODER = json.JSONDecoder()
OPTIONAL = {("payload", "turn_id"), ("payload", "internal_chat_message_metadata_passthrough"),
            ("payload", "internal_chat_message_metadata_passthrough", "turn_id")}


class StructuralProjection:
    def __init__(self, state=None):
        self.state = deepcopy(state) if state else {
            "stack": [], "value": {}, "token": None, "done": False,
            "error": False, "utf8": "",
        }

    def _fail(self):
        # Discard even partial scalar evidence after an unsupported structure.
        self.state.update(error=True, stack=[], token=None, utf8="", value={})

    def _path(self):
        stack = self.state["stack"]
        if not stack:
            return ()
        frame = stack[-1]
        path = frame["path"]
        key = frame.get("key")
        if path is not None and frame["kind"] == "object" and key in FIELDS.get(tuple(path), ()):
            return tuple(path) + (key,)
        return None

    def _store(self, path, value):
        if path is None or not path:
            return
        target = self.state["value"]
        for key in path[:-1]:
            target = target.setdefault(key, {})
        target[path[-1]] = value

    def _value_done(self):
        if self.state["stack"]:
            self.state["stack"][-1]["expect"] = "comma"
        else:
            self.state["done"] = True

    def _retain(self, text):
        token = self.state["token"]
        if token["raw"] is None:
            return
        if len(token["raw"]) + len(text) > MAX_HEADER_BYTES:
            if not token["key"]:
                self._fail()
            else:
                # A very long object key cannot equal a required header key.
                token["raw"] = None
        else:
            token["raw"] += text

    def _finish_token(self):
        token = self.state["token"]
        if token["kind"] == "scalar":
            path = tuple(token["path"]) if token["path"] is not None else None
            optional_null = path in OPTIONAL and token["scalar"].get("literal") == "null"
            if not scalar_complete(token["scalar"]) or (path is not None and not optional_null):
                self._fail()
            else:
                if optional_null:
                    self._store(path, None)
                self.state["token"] = None
                self._value_done()
            return
        try:
            value = DECODER.decode(token["raw"]) if token["raw"] is not None else None
        except (ValueError, RecursionError):
            self._fail()
            return
        self.state["token"] = None
        if token["key"]:
            frame = self.state["stack"][-1]
            required = FIELDS.get(tuple(frame["path"]), ()) if frame["path"] is not None else ()
            if value in required:
                if value in frame["seen"]:
                    self._fail()
                    return
                frame["seen"].append(value)
                frame["key"] = value
            else:
                frame["key"] = None
            frame["expect"] = "colon"
        else:
            if token["path"] is not None:
                if not isinstance(value, str) or len(value) > 256:
                    self._fail()
                    return
                self._store(token["path"], value)
            self._value_done()

    def feed(self, chunk: bytes):
        if self.state["error"]:
            return
        decoder = codecs.getincrementaldecoder("utf-8")()
        decoder.setstate((bytes.fromhex(self.state["utf8"]), 0))
        try:
            text = decoder.decode(chunk)
        except UnicodeDecodeError:
            self._fail()
            return
        self.state["utf8"] = decoder.getstate()[0].hex()
        index = 0
        while index < len(text) and not self.state["error"]:
            token = self.state["token"]
            char = text[index]
            if token is not None:
                if token["kind"] == "scalar":
                    if char in " \t\r\n,]}":
                        self._finish_token()
                        continue
                    if not advance_scalar(token["scalar"], char):
                        self._fail()
                        continue
                elif token["unicode"]:
                    if char not in "0123456789abcdefABCDEF":
                        self._fail()
                        continue
                    self._retain(char)
                    token["unicode"] -= 1
                elif token["escape"]:
                    if char not in '\\"/bfnrtu':
                        self._fail()
                        continue
                    self._retain(char)
                    token["escape"] = False
                    token["unicode"] = 4 if char == "u" else 0
                else:
                    match = SPECIAL.search(text, index)
                    end = match.start() if match else len(text)
                    self._retain(text[index:end])
                    index = end
                    if index >= len(text) or self.state["error"]:
                        continue
                    char = text[index]
                    self._retain(char)
                    if self.state["error"]:
                        continue
                    if char == '"':
                        self._finish_token()
                    elif char == "\\":
                        token["escape"] = True
                    else:
                        self._fail()
                index += 1
                continue
            if char in " \t\r\n":
                index += 1
                continue
            stack = self.state["stack"]
            frame = stack[-1] if stack else None
            expect = frame["expect"] if frame else "value"
            if self.state["done"]:
                self._fail()
            elif expect == "colon":
                if char != ":":
                    self._fail()
                else:
                    frame["expect"] = "value"
            elif char in "}]" and frame and (
                expect == "comma" or expect in {"key_or_end", "value_or_end"}
            ):
                if char != ("}" if frame["kind"] == "object" else "]"):
                    self._fail()
                else:
                    stack.pop()
                    self._value_done()
            elif expect == "comma":
                if char != ",":
                    self._fail()
                else:
                    frame["expect"] = "key" if frame["kind"] == "object" else "value"
            elif expect in {"key", "key_or_end"}:
                if char != '"':
                    self._fail()
                else:
                    self.state["token"] = {
                        "kind": "string", "key": True, "path": None,
                        "raw": '"' if frame["path"] is not None else None,
                        "escape": False, "unicode": 0,
                    }
            elif expect in {"value", "value_or_end"}:
                path = self._path()
                if not stack and char != "{":
                    self._fail()
                elif char in "{[":
                    if len(stack) >= MAX_DEPTH or (path is not None and path not in CONTAINERS and path != ()):
                        self._fail()
                    elif path in CONTAINERS and char != "{":
                        self._fail()
                    else:
                        if path in CONTAINERS:
                            self._store(path, {})
                        stack.append({
                            "kind": "object" if char == "{" else "array",
                            "path": list(path) if path is not None else None,
                            "expect": "key_or_end" if char == "{" else "value_or_end",
                            "key": None, "seen": [],
                        })
                elif path in CONTAINERS and not (path in OPTIONAL and char == "n"):
                    self._fail()
                elif char == '"':
                    self.state["token"] = {
                        "kind": "string", "key": False,
                        "path": list(path) if path is not None else None,
                        "raw": '"' if path is not None else None,
                        "escape": False, "unicode": 0,
                    }
                elif char in "-0123456789tfn":
                    self.state["token"] = {
                        "kind": "scalar", "key": False,
                        "path": list(path) if path is not None else None,
                        "scalar": begin_scalar(char),
                    }
                else:
                    self._fail()
            else:
                self._fail()
            index += 1

    def result(self):
        complete = self.state["done"] and not any(
            self.state[key] for key in ("error", "stack", "token", "utf8")
        )
        return self.state["value"], complete


def project_prefix(prefix: bytes) -> tuple[dict, bool]:
    projection = StructuralProjection()
    projection.feed(prefix)
    return projection.result()
