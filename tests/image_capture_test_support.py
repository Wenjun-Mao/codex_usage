from __future__ import annotations

import json


def session_meta(task_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:00Z",
        "type": "session_meta",
        "payload": {"id": task_id, "cwd": "/repo/image"},
    }


def turn_context() -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:01Z",
        "type": "turn_context",
        "payload": {"turn_id": "turn-image", "model": "gpt-5.6-terra"},
    }


def image_call(call_id: str, prompt: str) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:02Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "image_gen",
            "call_id": call_id,
            "arguments": json.dumps(
                {
                    "model": "gpt-image-2",
                    "size": "1024x1024",
                    "quality": "high",
                    "prompt": prompt,
                    "referenced_image_paths": ["/private/input.png"],
                }
            ),
        },
    }


def image_result(call_id: str, *, count: int) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(
                {
                    "model": "gpt-image-2",
                    "data": [{} for _ in range(count)],
                    "usage": {
                        "text_input_tokens": 10,
                        "cached_text_input_tokens": 0,
                        "image_input_tokens": 0,
                        "cached_image_input_tokens": 0,
                        "image_output_tokens": 20,
                        "total_tokens": 30,
                    },
                }
            ),
        },
    }


def image_failure(call_id: str) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps({"error": "generation failed"}),
        },
    }


def token_count(total_tokens: int) -> dict[str, object]:
    return {
        "timestamp": "2026-09-12T10:00:01Z",
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": total_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": total_tokens,
                }
            },
        },
    }
