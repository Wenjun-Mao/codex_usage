from codex_usage.models import TokenUsage


def test_token_usage_preserves_cache_write_category() -> None:
    usage = TokenUsage.from_mapping(
        {
            "input_tokens": 100,
            "cached_input_tokens": 60,
            "cache_write_input_tokens": 25,
            "output_tokens": 10,
            "reasoning_output_tokens": 4,
            "total_tokens": 110,
        }
    )

    assert usage.cache_write_input_tokens == 25
    assert usage.uncached_input_tokens == 40
    assert usage.ordinary_input_tokens == 15
    assert usage.to_dict()["cache_write_input_tokens"] == 25
    assert usage.to_dict()["ordinary_input_tokens"] == 15


def test_token_usage_defaults_absent_cache_write_category_to_zero() -> None:
    usage = TokenUsage.from_mapping(
        {
            "input_tokens": 100,
            "cached_input_tokens": 60,
            "output_tokens": 10,
            "reasoning_output_tokens": 4,
            "total_tokens": 110,
        }
    )

    assert usage.cache_write_input_tokens == 0
    assert usage.uncached_input_tokens == 40
    assert usage.ordinary_input_tokens == 40


def test_token_usage_add_and_positive_delta_preserve_cache_writes() -> None:
    first = TokenUsage(
        input_tokens=100,
        cached_input_tokens=60,
        cache_write_input_tokens=25,
        output_tokens=10,
        total_tokens=110,
    )
    current = TokenUsage(
        input_tokens=150,
        cached_input_tokens=90,
        cache_write_input_tokens=35,
        output_tokens=20,
        total_tokens=170,
    )

    delta = current.positive_delta(first)

    assert delta is not None
    assert delta.cache_write_input_tokens == 10
    assert first.add(delta).cache_write_input_tokens == 35
