# GPT-5.6 Cache-Write Pricing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve local Codex cache-write token counts and include their published GPT-5.6 premium in API-equivalent USD without changing Codex credit accounting.

**Architecture:** Extend the existing `TokenUsage` value object first so parsing, aggregation, and persistence share one explicit cache-write field. Extend API `ModelRate` and `CostBreakdown` separately from Codex credit rates, then expose the new category in the existing terminal, CSV, JSON, and HTML reporting paths. Rebuild the local SQLite cache so available source JSONL is reparsed, while legacy retained-missing rows use the documented zero default because their source evidence is unavailable.

**Tech Stack:** Python 3.13, dataclasses, SQLite, pytest, native HTML/CSS, VS Code extension packaging metadata, npm, Playwright CLI.

## Global Constraints

- Preserve exact model-id and explicit-alias matching; do not add GPT-5.6 family-prefix inference.
- Keep the GPT-5.6 API effective date at `2026-06-26T00:00:00Z` and Codex credit effective date at `2026-07-09T00:00:00Z`.
- Exactly 272,000 input tokens uses standard API rates; 272,001 uses long-context rates for the full retained request event.
- Cache writes use the ordinary input credit rate because the Codex rate card has no separate cache-write category.
- A missing `cache_write_input_tokens` field defaults to zero; never infer it from non-cached input.
- Active source files must be reparsed after the cache contract changes.
- Target version is `0.1.37`; do not tag, publish, or trigger release workflows as part of this plan.
- Keep all edits ASCII and avoid new runtime dependencies.

---

### Task 1: Preserve Cache-Write Tokens In The Domain And Parser

**Files:**
- Create: `tests/test_token_usage.py`
- Modify: `tests/test_parser_aggregation.py:18-36`
- Modify: `tests/test_parser_aggregation.py:647-658`
- Modify: `src/codex_usage/models.py:12-68`

**Interfaces:**
- Produces: `TokenUsage.cache_write_input_tokens: int`
- Produces: `TokenUsage.ordinary_input_tokens: int`
- Preserves: `TokenUsage.uncached_input_tokens == input_tokens - cached_input_tokens`
- Consumes upstream mapping key: `cache_write_input_tokens`

- [ ] **Step 1: Add failing `TokenUsage` contract tests**

Create `tests/test_token_usage.py`:

```python
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
```

- [ ] **Step 2: Add a failing parser-delta assertion**

Extend `_usage()` in `tests/test_parser_aggregation.py` with `cache_write: int = 0`, include the key in its returned mapping, and update `test_parser_uses_positive_cumulative_deltas`:

```python
_token(
    "2026-04-29T10:01:00Z",
    _usage(total=100, input_tokens=80, cached=20, cache_write=10, output=20),
),
_token(
    "2026-04-29T10:02:00Z",
    _usage(total=100, input_tokens=80, cached=20, cache_write=10, output=20),
),
_token(
    "2026-04-29T10:03:00Z",
    _usage(total=160, input_tokens=120, cached=30, cache_write=15, output=40),
),
```

Add these assertions:

```python
assert [record.usage.cache_write_input_tokens for record in records] == [10, 5]
assert summarize_records(records).usage.cache_write_input_tokens == 15
```

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
uv run pytest tests/test_token_usage.py tests/test_parser_aggregation.py::test_parser_uses_positive_cumulative_deltas -v
```

Expected: FAIL because `TokenUsage` has no cache-write field or ordinary-input property.

- [ ] **Step 4: Implement the value-object contract**

Update `TokenUsage` in `src/codex_usage/models.py`:

```python
@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0

    @property
    def uncached_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def ordinary_input_tokens(self) -> int:
        return max(0, self.input_tokens - self.cached_input_tokens - self.cache_write_input_tokens)
```

Add `cache_write_input_tokens` to `from_mapping()`, `add()`, `positive_delta()`, and `to_dict()`. Add `ordinary_input_tokens` to `to_dict()` while preserving every existing key.

- [ ] **Step 5: Run the domain and parser tests**

Run:

```bash
uv run pytest tests/test_token_usage.py tests/test_parser_aggregation.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the domain/parser change**

```bash
git add tests/test_token_usage.py tests/test_parser_aggregation.py src/codex_usage/models.py
git commit -m "feat: preserve cache-write token usage"
```

---

### Task 2: Price GPT-5.6 Cache Writes In API USD Only

**Files:**
- Modify: `tests/test_pricing.py:18-215`
- Modify: `tests/test_parser_aggregation.py:100-230`
- Modify: `src/codex_usage/pricing.py:9-285`

**Interfaces:**
- Consumes: `TokenUsage.ordinary_input_tokens`
- Consumes: `TokenUsage.cache_write_input_tokens`
- Produces: `ModelRate.cache_write_input_per_1m: float | None`
- Produces: `ModelRate.resolved_cache_write_input_per_1m: float`
- Produces: `CostBreakdown.ordinary_input_usd: float`
- Produces: `CostBreakdown.cache_write_input_usd: float`
- Preserves compatibility property: `CostBreakdown.uncached_input_usd`
- Preserves: `estimate_codex_credits()` behavior and public fields

- [ ] **Step 1: Add failing standard-rate tests**

Add this test to `tests/test_pricing.py`:

```python
@pytest.mark.parametrize(
    ("model", "write_rate"),
    (
        ("gpt-5.6-sol", 6.25),
        ("gpt-5.6-terra", 3.125),
        ("gpt-5.6-luna", 1.25),
    ),
)
def test_gpt_5_6_prices_cache_writes_separately(model: str, write_rate: float) -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        cached_input_tokens=250_000,
        cache_write_input_tokens=200_000,
        output_tokens=100_000,
        total_tokens=1_100_000,
    )

    rate = rate_for_model(model, at=GPT_5_6_API_EFFECTIVE_AT)
    cost = estimate_cost(usage, model, at=GPT_5_6_API_EFFECTIVE_AT)

    assert rate is not None
    assert rate.resolved_cache_write_input_per_1m == write_rate
    assert cost is not None
    assert cost.cache_write_input_usd == pytest.approx(0.2 * write_rate)
    assert cost.ordinary_input_usd == pytest.approx(usage.ordinary_input_tokens / 1_000_000 * rate.input_per_1m)
    assert cost.uncached_input_usd == pytest.approx(cost.ordinary_input_usd + cost.cache_write_input_usd)
```

- [ ] **Step 2: Add failing fallback and credit-invariance tests**

Add:

```python
def test_pre_gpt_5_6_cache_write_falls_back_to_input_rate() -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        cached_input_tokens=250_000,
        cache_write_input_tokens=200_000,
        output_tokens=100_000,
        total_tokens=1_100_000,
    )

    cost = estimate_cost(usage, "gpt-5.5")

    assert cost is not None
    assert cost.cache_write_input_usd == pytest.approx(1.0)
    assert cost.total_usd == pytest.approx(6.875)


def test_cache_writes_remain_normal_uncached_input_for_codex_credits() -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        cached_input_tokens=250_000,
        cache_write_input_tokens=200_000,
        output_tokens=100_000,
        total_tokens=1_100_000,
    )

    credits = estimate_codex_credits(usage, "gpt-5.6-sol", at=GPT_5_6_CREDIT_EFFECTIVE_AT)

    assert credits is not None
    assert credits.uncached_input_credits == pytest.approx(93.75)
    assert credits.cached_input_credits == pytest.approx(3.125)
    assert credits.output_credits == pytest.approx(75.0)
    assert credits.total_credits == pytest.approx(171.875)
```

- [ ] **Step 3: Add failing long-context cache-write cases**

Update the 272,000 and 272,001 tests so each usage has `cache_write_input_tokens=50_000`. At 272,000, Sol cache writes cost `$0.3125`; at 272,001 they cost `$0.625`. Parameterize long-context expectations for Terra (`$0.3125`) and Luna (`$0.125`) as well.

Assert the threshold still uses total `input_tokens`, not ordinary input tokens.

- [ ] **Step 4: Run pricing tests and verify failure**

Run:

```bash
uv run pytest tests/test_pricing.py tests/test_parser_aggregation.py -v
```

Expected: FAIL because rates and cost breakdowns have no cache-write component.

- [ ] **Step 5: Extend rates and long-context scaling**

Update `ModelRate`:

```python
@dataclass(frozen=True)
class ModelRate:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float
    cache_write_input_per_1m: float | None = None

    @property
    def resolved_cache_write_input_per_1m(self) -> float:
        return self.input_per_1m if self.cache_write_input_per_1m is None else self.cache_write_input_per_1m
```

In `RequestLevelLongContextPricing.apply()`, preserve `None`; otherwise multiply `cache_write_input_per_1m` by `input_rate_multiplier`. Extend `_effective_rate()` with an optional cache-write argument and set the GPT-5.6 API rows to `6.25`, `3.125`, and `1.25`. Do not set cache-write rates on Codex credit rows.

- [ ] **Step 6: Extend API cost breakdowns without changing credits**

Use this structure:

```python
@dataclass(frozen=True)
class CostBreakdown:
    ordinary_input_usd: float = 0.0
    cached_input_usd: float = 0.0
    cache_write_input_usd: float = 0.0
    output_usd: float = 0.0
    total_usd: float = 0.0
    unpriced_tokens: int = 0

    @property
    def uncached_input_usd(self) -> float:
        return self.ordinary_input_usd + self.cache_write_input_usd
```

Update `add()` to sum both new stored fields. Keep `uncached_input_usd` in `to_dict()` and add `ordinary_input_usd` plus `cache_write_input_usd`.

Update `estimate_cost()`:

```python
ordinary_input_usd = usage.ordinary_input_tokens / 1_000_000 * rate.input_per_1m
cached_input_usd = usage.cached_input_tokens / 1_000_000 * rate.cached_input_per_1m
cache_write_input_usd = (
    usage.cache_write_input_tokens / 1_000_000 * rate.resolved_cache_write_input_per_1m
)
output_usd = usage.output_tokens / 1_000_000 * rate.output_per_1m
total_usd = ordinary_input_usd + cached_input_usd + cache_write_input_usd + output_usd
```

Leave `estimate_codex_credits()` on `usage.uncached_input_tokens`.

- [ ] **Step 7: Update exact GPT-5.6 rate fixtures and pricing date**

Add explicit cache-write rates to GPT-5.6 API `ModelRate` expectations, retain `None` for credit expectations, and update `PRICING_AS_OF` plus its test to `2026-07-21`.

- [ ] **Step 8: Run focused pricing and aggregation tests**

Run:

```bash
uv run pytest tests/test_pricing.py tests/test_parser_aggregation.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit the pricing change**

```bash
git add tests/test_pricing.py tests/test_parser_aggregation.py src/codex_usage/pricing.py
git commit -m "fix: price GPT-5.6 cache writes"
```

---

### Task 3: Rebuild And Round-Trip The Persistent Usage Cache

**Files:**
- Modify: `tests/test_session_cache.py:13-155`
- Modify: `tests/test_session_cache.py:205-238`
- Modify: `src/codex_usage/session_cache.py:16-25`
- Modify: `src/codex_usage/session_cache.py:178-215`
- Modify: `src/codex_usage/session_cache.py:480-590`

**Interfaces:**
- Consumes: `TokenUsage.cache_write_input_tokens`
- Produces SQLite column: `usage_records.cache_write_input_tokens integer not null default 0`
- Changes: `CACHE_SCHEMA_VERSION` from `2` to `3`
- Changes: `PARSER_CACHE_VERSION` from `1` to `2`

- [ ] **Step 1: Make cache fixtures emit cache writes**

Change `_write_session()`, `_append_token_count()`, and `_token_count()` in `tests/test_session_cache.py` to accept `cache_write: int = 0`, and include:

```python
"cache_write_input_tokens": cache_write,
```

Update `test_first_cache_build_parses_and_stores_records` to write `cache_write=25` and assert:

```python
assert data.records[0].usage.cache_write_input_tokens == 25
```

- [ ] **Step 2: Add failing SQLite round-trip and rebuild assertions**

Extend `test_unchanged_file_is_reused_without_reparse` so the original file has `cache_write=25` and the reused record still has `25`.

Extend `test_schema_version_mismatch_rebuilds_cache` so the source has `cache_write=25`, then assert after rebuild:

```python
assert data.records[0].usage.cache_write_input_tokens == 25
assert data.stats.files_parsed == 1
```

- [ ] **Step 3: Add a failing legacy retained-missing migration test**

After creating and marking a source missing in `test_schema_rebuild_retains_missing_file_usage`, simulate the previous table shape:

```python
with sqlite3.connect(db_path) as connection:
    connection.execute("alter table usage_records drop column cache_write_input_tokens")
    connection.execute("update schema_meta set value = ? where key = 'schema_version'", ("2",))
    connection.execute("update schema_meta set value = ? where key = 'parser_version'", ("1",))
```

After rebuilding, assert the retained missing record survives with `cache_write_input_tokens == 0`.

- [ ] **Step 4: Run cache tests and verify failure**

Run:

```bash
uv run pytest tests/test_session_cache.py -v
```

Expected: FAIL because the schema and row mapping omit cache writes.

- [ ] **Step 5: Implement schema and row persistence**

Set:

```python
CACHE_SCHEMA_VERSION = 3
PARSER_CACHE_VERSION = 2
```

Add this column after `cached_input_tokens`:

```sql
cache_write_input_tokens integer not null default 0,
```

Add the column to `_insert_record()` SQL and values, then populate it in `_row_to_record()`:

```python
cache_write_input_tokens=int(row["cache_write_input_tokens"]),
```

The `default 0` must remain in the schema so `_insert_dict_rows()` can restore a legacy retained-missing row whose snapshot lacks the column.

- [ ] **Step 6: Run cache and parser tests**

Run:

```bash
uv run pytest tests/test_session_cache.py tests/test_parser_aggregation.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit the cache migration**

```bash
git add tests/test_session_cache.py src/codex_usage/session_cache.py
git commit -m "feat: cache cache-write token usage"
```

---

### Task 4: Expose Cache Reads And Writes In Reports

**Files:**
- Modify: `tests/test_cli.py:12-92`
- Modify: `tests/test_reporting_html.py:10-72`
- Modify: `tests/test_reporting_html.py:161-190`
- Modify: `src/codex_usage/reporting.py:70-125`
- Modify: `src/codex_usage/reporting.py:211-260`
- Modify: `src/codex_usage/reporting.py:335-400`

**Interfaces:**
- Consumes: `TokenUsage.cache_write_input_tokens`
- Consumes: `TokenUsage.ordinary_input_tokens`
- Produces CSV fields: `cache_write_input_tokens`, `ordinary_input_tokens`
- Produces terminal/HTML labels: `Cache Read`, `Cache Write`

- [ ] **Step 1: Add failing JSON, CSV, terminal, and HTML assertions**

In `tests/test_cli.py`, add `"cache_write_input_tokens": 10` to the sample event and assert:

```python
assert payload["total"]["usage"]["cache_write_input_tokens"] == 10
assert payload["total"]["usage"]["ordinary_input_tokens"] == 65
assert "cache_write_input_tokens" in csv_result.stdout
assert "ordinary_input_tokens" in csv_result.stdout

terminal_result = _run_cli(["summary", "--range", "all", "--by", "day"], env=env)
assert "Cache Read" in terminal_result.stdout
assert "Cache Write" in terminal_result.stdout
```

In `tests/test_reporting_html.py`, give the total and one row nonzero cache writes, then assert:

```python
assert '<th class="num">Cache Read</th>' in html
assert '<th class="num">Cache Write</th>' in html
assert '<td class="num">125</td>' in html
```

- [ ] **Step 2: Add a failing retained-missing evidence warning assertion**

Extend `test_report_html_mentions_archived_and_retained_missing_files`:

```python
assert "newer token details may be unavailable until source files are restored" in html
```

- [ ] **Step 3: Run reporting tests and verify failure**

Run:

```bash
uv run pytest tests/test_cli.py::test_cli_summary_json_csv_and_report tests/test_reporting_html.py -v
```

Expected: FAIL because CSV and visible reports omit cache writes.

- [ ] **Step 4: Extend CSV and terminal rendering**

Add `cache_write_input_tokens` and `ordinary_input_tokens` to `_write_csv_rows()` field names and row values.

Change terminal headers from `Cached` to `Cache Read` and add `Cache Write`. Extend `_format_row()` with a `cache_write` argument and pass it for totals and every row.

Use stable widths so long labels do not shift other columns:

```python
return (
    f"{'Label':<34} {'Total':>14} {'Input':>14} {'Cache Read':>14} "
    f"{'Cache Write':>14} {'Output':>14} {'Cost':>11} {'Credits':>12} "
    f"{'API Excl.':>14} {'No Credit':>14}"
)
```

- [ ] **Step 5: Extend HTML tables and retained-missing copy**

Insert a cache-write cell after cached input and change the headers:

```python
f"<td class=\"num\">{_fmt_int(row.usage.cached_input_tokens)}</td>"
f"<td class=\"num\">{_fmt_int(row.usage.cache_write_input_tokens)}</td>"
```

```html
<th class="num">Cache Read</th><th class="num">Cache Write</th>
```

When `files_retained_missing` is nonzero, append this storage summary bit:

```text
Newer token details may be unavailable until source files are restored
```

Keep table overflow handled by the existing `.table-wrap`; do not shrink fonts dynamically.

- [ ] **Step 6: Run CLI and report tests**

Run:

```bash
uv run pytest tests/test_cli.py tests/test_reporting_html.py tests/test_report_view.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit reporting changes**

```bash
git add tests/test_cli.py tests/test_reporting_html.py src/codex_usage/reporting.py
git commit -m "feat: report cache reads and writes"
```

---

### Task 5: Update The Durable Contract, User Documentation, And Version

**Files:**
- Create: `docs/adr/0015-explicit-token-category-accounting.md`
- Modify: `docs/adr/README.md`
- Modify: `docs/superpowers/specs/2026-07-09-gpt-5-6-pricing-design.md:58-69`
- Modify: `README.md:145-165`
- Modify: `extensions/vscode/README.md:110-130`
- Modify: `CHANGELOG.md:3-5`
- Modify: `extensions/vscode/CHANGELOG.md:3-5`
- Modify: `pyproject.toml:1-5`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json:1-8`
- Modify: `extensions/vscode/package-lock.json`
- Modify: `tests/test_task_transfer_docs.py:18-65`
- Modify: `tests/test_github_actions_workflow.py:108-118`

**Interfaces:**
- Produces release version: `0.1.37`
- Produces ADR 0015 guardrail for explicit upstream token categories
- Replaces stale user-facing cache-write limitation text

- [ ] **Step 1: Add failing documentation and version guardrails**

Add to `tests/test_task_transfer_docs.py`:

```python
def test_current_docs_describe_observed_cache_write_accounting() -> None:
    for path in CURRENT_DOCS:
        prose = normalized_prose(path.read_text(encoding="utf-8"))
        assert "cache_write_input_tokens" in prose
        assert "cannot include" not in prose
        assert "no distinct cache-write token count" not in prose
```

Add `"0.1.37": "2026-07-21"` to `ROOT_RELEASE_DATES` and prepend `"0.1.37"` to `EXTENSION_RELEASE_VERSIONS`.

Change expected versions in `tests/test_github_actions_workflow.py` from `0.1.36` to `0.1.37`.

- [ ] **Step 2: Run documentation/version tests and verify failure**

Run:

```bash
uv run pytest tests/test_task_transfer_docs.py tests/test_github_actions_workflow.py -v
```

Expected: FAIL on stale README language and version `0.1.36`.

- [ ] **Step 3: Add ADR 0015 and index it**

Create `docs/adr/0015-explicit-token-category-accounting.md` with:

```markdown
# ADR 0015: Explicit Token Category Accounting

Status: Accepted

Date: 2026-07-21

## Context

Codex token events can expose distinct categories that overlap broader totals. GPT-5.6 cache writes are included in non-cached input but have a separate API rate. Dropping that field caused API-equivalent USD to miss the cache-write premium.

## Decision

Preserve every explicit upstream token category through parsing, cumulative deltas, persistence, aggregation, serialization, and reporting. Never reconstruct a missing category from another total.

API USD and Codex credits may intentionally classify the same token differently when their official rate cards differ. Cache writes use the published cache-write API rate but remain ordinary input for Codex credits until an official credit rate says otherwise.

## Alternatives Considered

- Infer cache writes from non-cached input. Rejected because ordinary uncached input can coexist with writes.
- Keep only broad totals. Rejected because it discards billable evidence.
- Fetch live billing data. Rejected because reporting remains local and deterministic.

## Consequences

Usage schema changes require a parser-cache rebuild. Missing source files cannot gain categories introduced after they were cached, so reports disclose that evidence limitation.

## Guardrails

- Keep upstream field names at ingestion boundaries.
- Use checked-in, effective-dated rates.
- Do not add a Codex-credit category without an official rate card.
- Default absent optional fields to zero; do not infer values.
```

Add ADR 0015 to `docs/adr/README.md`.

- [ ] **Step 4: Correct pricing documentation and changelogs**

Replace README limitation text with wording that says local Codex logs expose `cache_write_input_tokens`, GPT-5.6 API-equivalent USD prices it at 1.25 times ordinary input, and Codex credits still have no separate write category.

Add this release heading to both changelogs:

```markdown
## 0.1.37 - 2026-07-21 - GPT-5.6 Cache-Write Accounting

- Preserved Codex cache-write token counts through parsing, local caching, aggregation, JSON, CSV, terminal, and HTML reports.
- Applied the published GPT-5.6 cache-write API rates, including long-context multipliers, while keeping Codex credits on their published input rate.
- Rebuilt available cached source data and disclosed the evidence limitation for retained records whose source JSONL is missing.
```

Add a supersession note to the old GPT-5.6 design rather than rewriting its historical decision.

- [ ] **Step 5: Bump package metadata mechanically**

Set both package manifests to `0.1.37`, then run:

```bash
uv lock
```

```bash
npm install --package-lock-only --ignore-scripts
```

Run the npm command from `extensions/vscode`.

- [ ] **Step 6: Run documentation and metadata tests**

Run:

```bash
uv run pytest tests/test_task_transfer_docs.py tests/test_github_actions_workflow.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit documentation and version changes**

```bash
git add docs/adr docs/superpowers/specs/2026-07-09-gpt-5-6-pricing-design.md README.md extensions/vscode/README.md CHANGELOG.md extensions/vscode/CHANGELOG.md pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json tests/test_task_transfer_docs.py tests/test_github_actions_workflow.py
git commit -m "docs: document cache-write accounting"
```

---

### Task 6: Refresh Visual Evidence And Run Full Verification

**Files:**
- Modify: `docs/marketplace/dashboard-synthetic.png`

**Interfaces:**
- Verifies the HTML table at `1440x900` and `390x844`
- Produces an updated synthetic Marketplace screenshot with no private data

- [ ] **Step 1: Generate a synthetic report with visible cache writes**

Create an ephemeral Codex home with two synthetic projects and nonzero cache writes:

```bash
uv run python - <<'PY'
import json
import shutil
from pathlib import Path


codex_home = Path("/tmp/codex-usage-cache-write-screenshot")
shutil.rmtree(codex_home, ignore_errors=True)
day = codex_home / "sessions" / "2026" / "07" / "20"
day.mkdir(parents=True)

sessions = (
    (
        "synthetic-sol",
        "/synthetic/research-dashboard",
        "https://github.com/example/research-dashboard.git",
        "gpt-5.6-sol",
        {
            "input_tokens": 320_000,
            "cached_input_tokens": 240_000,
            "cache_write_input_tokens": 60_000,
            "output_tokens": 20_000,
            "reasoning_output_tokens": 8_000,
            "total_tokens": 340_000,
        },
    ),
    (
        "synthetic-terra",
        "/synthetic/automation-tools",
        "https://github.com/example/automation-tools.git",
        "gpt-5.6-terra",
        {
            "input_tokens": 150_000,
            "cached_input_tokens": 100_000,
            "cache_write_input_tokens": 40_000,
            "output_tokens": 10_000,
            "reasoning_output_tokens": 3_000,
            "total_tokens": 160_000,
        },
    ),
)

for index, (session_id, cwd, repository_url, model, usage) in enumerate(sessions):
    minute = index * 15
    rows = [
        {
            "timestamp": f"2026-07-20T14:{minute:02d}:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": f"2026-07-20T14:{minute:02d}:00Z",
                "cwd": cwd,
                "git": {"repository_url": repository_url},
            },
        },
        {
            "timestamp": f"2026-07-20T14:{minute:02d}:01Z",
            "type": "turn_context",
            "payload": {"turn_id": f"turn-{session_id}", "model": model, "effort": "medium"},
        },
        {
            "timestamp": f"2026-07-20T14:{minute:02d}:02Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        },
    ]
    (day / f"{session_id}.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
PY
```

Generate the report:

```bash
CODEX_HOME=/tmp/codex-usage-cache-write-screenshot uv run codex-usage report --range all --theme night --output /tmp/codex-usage-cache-write-report.html
```

Confirm the HTML contains both headers:

```bash
rg -n "Cache Read|Cache Write" /tmp/codex-usage-cache-write-report.html
```

Expected: both labels appear in the detail-table header.

- [ ] **Step 2: Capture desktop and narrow screenshots**

Install the browser only if Playwright reports it missing:

```bash
npx playwright install chromium
```

Capture:

```bash
npx playwright screenshot --browser chromium --viewport-size "1440,900" file:///tmp/codex-usage-cache-write-report.html docs/marketplace/dashboard-synthetic.png
```

```bash
npx playwright screenshot --browser chromium --viewport-size "390,844" file:///tmp/codex-usage-cache-write-report.html /tmp/codex-usage-cache-write-mobile.png
```

Inspect both images. Verify the table scroll container contains the added column, no header overlaps another header, and no text escapes its parent.

- [ ] **Step 3: Run formatting and complete Python tests**

Run:

```bash
uvx ruff check .
```

Expected: exit 0.

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Run the complete VS Code extension suite**

From `extensions/vscode`, run:

```bash
npm test
```

Expected: TypeScript build and all Node tests pass.

- [ ] **Step 5: Verify package metadata and repository state**

Run:

```bash
git diff --check
```

```bash
git status --short
```

Expected: no whitespace errors; only the intended screenshot remains uncommitted after prior task commits.

- [ ] **Step 6: Commit the refreshed screenshot**

```bash
git add docs/marketplace/dashboard-synthetic.png
git commit -m "docs: refresh cache-write dashboard screenshot"
```

- [ ] **Step 7: Perform final review**

Review the complete branch diff against `docs/superpowers/specs/2026-07-21-gpt-5-6-cache-write-pricing-design.md`. Confirm:

- cache writes survive source JSONL through every output;
- API USD uses full cache-write rates, not only the uplift;
- Codex credits are unchanged;
- long-context scaling applies at the request-event boundary;
- stale limitation wording is gone from current user documentation;
- no tag, push, release, or publish action has occurred.
