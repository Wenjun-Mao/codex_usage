import json
from unittest.mock import patch

import pytest

from codex_usage.parser import parse_session_generation, parse_session_append
from codex_usage.session_chunk_reader import CandidateRow
from speed_test_support import append_rows, write_source


def exact_row(handle, stop_offset, **kwargs):
    raw = handle.readline(stop_offset - handle.tell())
    return CandidateRow(raw, raw.endswith(b"\n"), len(raw), "relevant")


@pytest.mark.parametrize("ascii_json", [True, False])
def test_long_unicode_image_call_preserves_exact_metadata_and_repo_candidates(tmp_path, ascii_json):
    path = write_source(tmp_path, count=0)
    # Put Unicode in the first prefix and metadata after the long prompt.
    arguments = {"model": "gpt-image-2", "prompt": "\u4e2d" + "x" * 10000,
                 "size": "1024x1536", "quality": "high", "output_format": "webp",
                 "referenced_image_paths": ["/synthetic/reference.png"]}
    row = {"timestamp": "2026-10-08T12:00:01Z", "type": "response_item", "payload": {
        "type": "function_call", "name": "image_gen", "call_id": "synthetic-image",
        "arguments": json.dumps(arguments, ensure_ascii=ascii_json)}}
    with path.open("a") as stream:
        stream.write(json.dumps(row, ensure_ascii=ascii_json) + "\n")
    repo_call = {"timestamp": "2026-10-08T12:00:02Z", "type": "response_item", "payload": {
        "type": "function_call", "name": "exec_command", "call_id": "synthetic-repo",
        "arguments": json.dumps({"command": "\u4e2d" + "x" * 10000, "workdir": "/synthetic/\u4e2d-repo"}, ensure_ascii=ascii_json)}}
    with path.open("a") as stream:
        stream.write(json.dumps(repo_call, ensure_ascii=ascii_json) + "\n")
    with patch("codex_usage.session_parser_incremental.read_candidate_row", exact_row):
        expected = parse_session_generation(path)
    actual = parse_session_generation(path)
    assert actual.image_operations == expected.image_operations
    assert actual.candidates == expected.candidates and len(actual.candidates) == 1
    operation = actual.image_operations[0]
    assert (operation.output_width, operation.output_height, operation.quality, operation.output_format) == (1024, 1536, "high", "webp")
    assert operation.kind.value == "edit_reference"
    assert actual.records == expected.records
    first = parse_session_generation(path, stop_offset=path.read_bytes().index(b"\n") + 1)
    appended = parse_session_append(path, first.checkpoint, stop_offset=path.stat().st_size,
                                    max_bytes=16 * 1024 * 1024, strict_byte_budget=True)
    assert appended.image_operations == expected.image_operations
    assert appended.candidates == expected.candidates


def test_large_unicode_message_body_still_uses_content_free_projection(tmp_path):
    from codex_usage.session_parser_models import parser_state_to_json
    path = write_source(tmp_path, count=0)
    append_rows(path, [{"type": "response_item", "payload": {"type": "message", "role": "user",
        "content": [{"text": "\u4e2d" * 10000}]}}])
    chunk = parse_session_generation(path, max_bytes=8000, strict_byte_budget=True)
    assert chunk.checkpoint.state.row_drain
    assert "\\u4e2d" not in parser_state_to_json(chunk.checkpoint.state)
