from codex_usage.model_presentation import (
    assign_model_color_slots,
    model_display_sort_key,
)


def test_model_display_order_prefers_generation_then_product_tier() -> None:
    models = [
        "unknown",
        "gpt-5.4-mini",
        "gpt-5.6-luna",
        "gpt-5.3-codex-spark",
        "gpt-5.6-sol",
        "gpt-6-astra",
        "gpt-6-luna",
        "gpt-6-sol",
        "gpt-6.1-sol",
        "gpt-5.5",
        "gpt-5.6-terra",
        "gpt-5.4",
    ]

    assert sorted(models, key=model_display_sort_key) == [
        "gpt-6.1-sol",
        "gpt-6-astra",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex-spark",
        "unknown",
    ]


def test_known_model_colors_are_stable_and_remaining_slots_are_unique() -> None:
    models = (
        "gpt-6-astra",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    )
    slots = assign_model_color_slots((*models, "gpt-5.5"))

    assert slots == {
        "gpt-6-astra": 0,
        "gpt-6-sol": 4,
        "gpt-6-luna": 5,
        "gpt-5.6-sol": 1,
        "gpt-5.6-terra": 2,
        "gpt-5.6-luna": 3,
        "gpt-5.5": 6,
    }
    assert assign_model_color_slots((*models, "gpt-6.1-sol")) == {
        **{model: slot for model, slot in slots.items() if model != "gpt-5.5"},
        "gpt-6.1-sol": 6,
    }
