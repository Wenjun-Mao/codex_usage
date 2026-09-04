from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple


BEDROCK_GPT_5_6_API_EFFECTIVE_FROM = datetime(2026, 7, 13, tzinfo=UTC)
BEDROCK_GPT_5_6_TERRA_LUNA_API_REDUCTION_EFFECTIVE_FROM = datetime(
    2026,
    7,
    30,
    tzinfo=UTC,
)
BEDROCK_GPT_5_6_SOL_API_REDUCTION_EFFECTIVE_FROM = datetime(
    2026,
    8,
    21,
    tzinfo=UTC,
)


class BedrockRateRow(NamedTuple):
    model_key: str
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float
    cache_write_input_per_1m: float
    effective_from: datetime
    aliases: tuple[str, ...] = ()


# Amazon Bedrock Standard In-Region rates. These rows preserve the historical
# rates before each model's later reduction. The us./in. inference-profile IDs
# use the same rates as In-Region where documented; global.* IDs are omitted
# because their rates differ.
BEDROCK_API_RATE_ROWS: tuple[BedrockRateRow, ...] = (
    BedrockRateRow(
        "openai.gpt-5.6-sol",
        5.50,
        0.55,
        33.00,
        6.875,
        BEDROCK_GPT_5_6_API_EFFECTIVE_FROM,
        ("us.openai.gpt-5.6-sol",),
    ),
    BedrockRateRow(
        "openai.gpt-5.6-terra",
        2.75,
        0.275,
        16.50,
        3.4375,
        BEDROCK_GPT_5_6_API_EFFECTIVE_FROM,
        ("us.openai.gpt-5.6-terra", "in.openai.gpt-5.6-terra"),
    ),
    BedrockRateRow(
        "openai.gpt-5.6-luna",
        1.10,
        0.11,
        6.60,
        1.375,
        BEDROCK_GPT_5_6_API_EFFECTIVE_FROM,
        ("us.openai.gpt-5.6-luna",),
    ),
    BedrockRateRow(
        "openai.gpt-5.6-sol",
        4.40,
        0.44,
        22.00,
        5.50,
        BEDROCK_GPT_5_6_SOL_API_REDUCTION_EFFECTIVE_FROM,
        ("us.openai.gpt-5.6-sol",),
    ),
    BedrockRateRow(
        "openai.gpt-5.6-terra",
        2.20,
        0.22,
        13.20,
        2.75,
        BEDROCK_GPT_5_6_TERRA_LUNA_API_REDUCTION_EFFECTIVE_FROM,
        ("us.openai.gpt-5.6-terra", "in.openai.gpt-5.6-terra"),
    ),
    BedrockRateRow(
        "openai.gpt-5.6-luna",
        0.22,
        0.022,
        1.32,
        0.275,
        BEDROCK_GPT_5_6_TERRA_LUNA_API_REDUCTION_EFFECTIVE_FROM,
        ("us.openai.gpt-5.6-luna",),
    ),
)
