from __future__ import annotations

from collections.abc import Sequence

from codex_usage.parallel.usage import UsageParseRequest, UsageParseResult


def validated_results(
    requests: Sequence[UsageParseRequest],
    results: Sequence[UsageParseResult],
) -> tuple[UsageParseResult, ...]:
    if len(results) != len(requests):
        raise ValueError("usage parse result count does not match request count")
    expected_by_ordinal = {request.ordinal: request for request in requests}
    if len(expected_by_ordinal) != len(requests):
        raise ValueError("usage parse requests contain duplicate ordinals")

    seen: set[int] = set()
    for result in results:
        ordinal = result.request.ordinal
        if ordinal in seen:
            raise ValueError("usage parse results contain duplicate ordinals")
        if expected_by_ordinal.get(ordinal) != result.request:
            raise ValueError("usage parse result does not match its request")
        seen.add(ordinal)
    if seen != set(expected_by_ordinal):
        raise ValueError("usage parse results do not cover the complete request group")
    return tuple(sorted(results, key=lambda result: result.request.ordinal))
