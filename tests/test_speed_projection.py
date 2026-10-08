import json
import random

import pytest

from codex_usage.speed_projection import StructuralProjection, project_prefix


@pytest.mark.parametrize("stride", [1, 2, 7, 4096])
def test_structural_projection_skips_content_preserves_late_headers_and_restart(stride):
    obj = {"timestamp": "2026-10-08T12:00:00Z", "type": "response_item", "payload": {
        "type": "message", "role": "assistant",
        "content": [{"text": 'private\\escape \" fake turn_id \u4e2d ' * 200},
                    {"nested": [None, True, False, -123.5e22, {"turn_id": "FAKE"}]}],
        "internal_chat_message_metadata_passthrough": {"turn_id": "real-turn"},
    }}
    raw = json.dumps(obj, ensure_ascii=False).encode()
    projection = StructuralProjection()
    for offset in range(0, len(raw), stride):
        projection.feed(raw[offset:offset + stride])
        state = json.dumps(projection.state)
        assert len(state) < 12000 and "private" not in state and "FAKE" not in state
        projection = StructuralProjection(json.loads(state))
    result, complete = projection.result()
    assert complete
    assert result == {"timestamp": obj["timestamp"], "type": obj["type"], "payload": {
        "type": "message", "role": "assistant",
        "internal_chat_message_metadata_passthrough": {"turn_id": "real-turn"}}}


@pytest.mark.parametrize("raw", [
    b'{"type":"response_item","type":"event_msg"}',
    b'{"payload":{"turn_id":"A","turn_id":"B"}}',
    b'{"payload":[]}', b'{"type":123}', b'{"payload":{"content":"bad\\z"}}',
    b'{"payload":{"content":"bad\x01"}}', b'{"payload":{"content":"bad\xff"}}',
    b'{"payload":{"content":01}}', b'{"payload":{"content":1.}}',
    b'{"payload":{"content":1e+}}', b'{"payload":{"content":tru}}',
    b'{"payload":{"content":[1,]}}', b'{"payload":{"content":{ "a":1,}}}',
    b'{"payload":{}}{}',
])
def test_invalid_structure_or_conflicting_headers_are_unsafe(raw):
    assert not project_prefix(raw)[1]


def test_structural_state_bounds_and_explicit_unsupported_format():
    projection = StructuralProjection()
    projection.feed(b'{"payload":{"content":' + b"[" * 65)
    assert projection.state["error"] and len(json.dumps(projection.state)) < 200
    projection = StructuralProjection()
    projection.feed(b'{"payload":{"content":"' + b"x" * 1000000)
    assert len(json.dumps(projection.state)) < 2000 and not projection.result()[1]
    projection.feed(b'","' + b"x" * 100000 + b'":null,"role":"assistant"}}')
    assert projection.result()[1]


def test_ignored_numbers_are_grammar_only_not_retained_in_checkpoint():
    projection = StructuralProjection()
    projection.feed(b'{"payload":{"content":123456789123456789')
    assert "123456" not in json.dumps(projection.state)
    projection.feed(b'}}')
    assert projection.result()[1]


@pytest.mark.parametrize("stride", [1, 7, 4096])
def test_seeded_structural_extraction_matches_whole_headers(stride):
    randomizer = random.Random(2110)
    for _ in range(100):
        metadata = randomizer.choice([None, {}, {"turn_id": None}, {"turn_id": "known-turn"}])
        body = {"type": "message", "role": "assistant", "internal_chat_message_metadata_passthrough": metadata,
                "content": ["private\\escaped \" \u4e2d", {"turn_id": "FAKE", "nested": [None, True, -1.23e30]}]}
        pairs = list(body.items())
        randomizer.shuffle(pairs)
        outer = [("type", "response_item"), ("timestamp", "2026-10-08T12:00:00Z"), ("payload", dict(pairs))]
        randomizer.shuffle(outer)
        raw = json.dumps(dict(outer), ensure_ascii=randomizer.choice([True, False])).encode()
        projection = StructuralProjection()
        for index in range(0, len(raw), stride):
            projection.feed(raw[index:index + stride])
            projection = StructuralProjection(json.loads(json.dumps(projection.state)))
        assert projection.result() == ({"type": "response_item", "timestamp": "2026-10-08T12:00:00Z",
            "payload": {"type": "message", "role": "assistant", "internal_chat_message_metadata_passthrough": metadata}}, True)
