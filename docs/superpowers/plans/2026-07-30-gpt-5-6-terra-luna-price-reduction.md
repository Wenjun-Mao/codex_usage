# GPT-5.6 Terra And Luna Price Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply reduced GPT-5.6 Terra and Luna Standard API-equivalent USD rates from `2026-07-31T00:00:00Z` while preserving all earlier estimates, GPT-5.6 Sol pricing, and Codex credit rates.

**Architecture:** Extend the checked-in API pricing schedule with one later effective-dated row for Terra and one for Luna. Reuse the existing latest-applicable-row lookup and GPT-5.6 request-level long-context contract; no parser, cache, schema, report, or network behavior changes are needed.

**Tech Stack:** Python 3.12, dataclasses, pytest, uv, Node.js/npm, VS Code extension packaging, PyInstaller, VSCE

## Global Constraints

- Use `2026-07-31T00:00:00Z` as the exact API pricing transition.
- Preserve the original Terra and Luna rows effective from `2026-06-26T00:00:00Z`.
- Use the reduced Standard Terra rates per 1M tokens: ordinary input `$2.00`, cached input `$0.20`, cache write `$2.50`, output `$12.00`.
- Use the reduced Standard Luna rates per 1M tokens: ordinary input `$0.20`, cached input `$0.02`, cache write `$0.25`, output `$1.20`.
- Keep the long-context threshold at more than `272,000` input tokens and keep its existing `2x` input-category and `1.5x` output multipliers.
- Keep GPT-5.6 Sol API pricing unchanged.
- Do not modify `CODEX_CREDIT_RATE_SCHEDULE`; Terra and Luna Codex credit estimates remain unchanged.
- Keep reasoning effort as metadata with no rate multiplier.
- Do not add live pricing fetches or change Batch, Flex, or Fast mode behavior.
- Prepare release `0.1.41`, dated `2026-07-30`, for Python and the VS Code extension.
- Historical changelog entries, design records, and ADR 0003 remain unchanged.

---

### Task 1: Add The Effective-Dated Terra And Luna API Rates

**Files:**
- Modify: `tests/test_pricing.py`
- Modify: `src/codex_usage/pricing.py`

**Interfaces:**
- Consumes: `rate_for_model(model: str, at: datetime | None = None) -> ModelRate | None`, `credit_rate_for_model(model: str, at: datetime | None = None) -> ModelRate | None`, and `estimate_cost(usage: TokenUsage, model: str, at: datetime | None = None) -> CostBreakdown | None`.
- Produces: `GPT_5_6_TERRA_LUNA_API_REDUCTION_EFFECTIVE_FROM: datetime` and two additional entries in `API_PRICING_USD_SCHEDULE`.
- Preserves: the existing `GPT_5_6_API_LONG_CONTEXT_PRICING` contract and every entry in `CODEX_CREDIT_RATE_SCHEDULE`.

- [ ] **Step 1: Add boundary and latest-rate regression tests**

In `tests/test_pricing.py`, keep `GPT_5_6_RATE_CASES` and its June 26 tests unchanged. Add these constants and tests after the existing GPT-5.6 effective-date coverage:

```python
GPT_5_6_TERRA_LUNA_API_REDUCTION_AT = datetime(2026, 7, 31, tzinfo=UTC)
GPT_5_6_TERRA_LUNA_API_REDUCTION_BEFORE = datetime(
    2026,
    7,
    30,
    23,
    59,
    59,
    999_999,
    tzinfo=UTC,
)

GPT_5_6_TERRA_LUNA_REDUCTION_CASES = (
    (
        "gpt-5.6-terra",
        ModelRate(
            input_per_1m=2.5,
            cached_input_per_1m=0.25,
            output_per_1m=15.0,
            cache_write_input_per_1m=3.125,
        ),
        ModelRate(
            input_per_1m=2.0,
            cached_input_per_1m=0.2,
            output_per_1m=12.0,
            cache_write_input_per_1m=2.5,
        ),
    ),
    (
        "gpt-5.6-luna",
        ModelRate(
            input_per_1m=1.0,
            cached_input_per_1m=0.1,
            output_per_1m=6.0,
            cache_write_input_per_1m=1.25,
        ),
        ModelRate(
            input_per_1m=0.2,
            cached_input_per_1m=0.02,
            output_per_1m=1.2,
            cache_write_input_per_1m=0.25,
        ),
    ),
)


@pytest.mark.parametrize(
    ("model", "original_rate", "reduced_rate"),
    GPT_5_6_TERRA_LUNA_REDUCTION_CASES,
)
def test_terra_and_luna_api_reduction_uses_exact_effective_boundary(
    model: str,
    original_rate: ModelRate,
    reduced_rate: ModelRate,
) -> None:
    assert (
        rate_for_model(model, at=GPT_5_6_TERRA_LUNA_API_REDUCTION_BEFORE)
        == original_rate
    )
    assert (
        rate_for_model(model, at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT)
        == reduced_rate
    )
    assert rate_for_model(model) == reduced_rate


def test_terra_and_luna_reduction_does_not_change_sol_or_codex_credit_rates() -> None:
    assert rate_for_model(
        "gpt-5.6-sol",
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    ) == ModelRate(
        input_per_1m=5.0,
        cached_input_per_1m=0.5,
        output_per_1m=30.0,
        cache_write_input_per_1m=6.25,
    )
    assert credit_rate_for_model(
        "gpt-5.6-terra",
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    ) == ModelRate(
        input_per_1m=62.5,
        cached_input_per_1m=6.25,
        output_per_1m=375.0,
    )
    assert credit_rate_for_model(
        "gpt-5.6-luna",
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    ) == ModelRate(
        input_per_1m=25.0,
        cached_input_per_1m=2.5,
        output_per_1m=150.0,
    )
```

- [ ] **Step 2: Add short- and long-context cost regression tests**

Add tests that exercise every input category and output at the reduced rates:

```python
@pytest.mark.parametrize(
    (
        "model",
        "expected_ordinary",
        "expected_cached",
        "expected_cache_write",
        "expected_output",
        "expected_total",
    ),
    (
        ("gpt-5.6-terra", 0.3, 0.0144, 0.125, 1.2, 1.6394),
        ("gpt-5.6-luna", 0.03, 0.00144, 0.0125, 0.12, 0.16394),
    ),
)
def test_terra_and_luna_reduced_short_context_costs(
    model: str,
    expected_ordinary: float,
    expected_cached: float,
    expected_cache_write: float,
    expected_output: float,
    expected_total: float,
) -> None:
    usage = TokenUsage(
        input_tokens=272_000,
        cached_input_tokens=72_000,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=372_000,
    )

    cost = estimate_cost(
        usage,
        model,
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    )

    assert cost is not None
    assert cost.ordinary_input_usd == pytest.approx(expected_ordinary)
    assert cost.cached_input_usd == pytest.approx(expected_cached)
    assert cost.cache_write_input_usd == pytest.approx(expected_cache_write)
    assert cost.output_usd == pytest.approx(expected_output)
    assert cost.total_usd == pytest.approx(expected_total)


@pytest.mark.parametrize(
    (
        "model",
        "expected_ordinary",
        "expected_cached",
        "expected_cache_write",
        "expected_output",
        "expected_total",
    ),
    (
        ("gpt-5.6-terra", 0.6, 0.0288004, 0.25, 1.8, 2.6788004),
        ("gpt-5.6-luna", 0.06, 0.00288004, 0.025, 0.18, 0.26788004),
    ),
)
def test_terra_and_luna_reduced_long_context_costs(
    model: str,
    expected_ordinary: float,
    expected_cached: float,
    expected_cache_write: float,
    expected_output: float,
    expected_total: float,
) -> None:
    usage = TokenUsage(
        input_tokens=272_001,
        cached_input_tokens=72_001,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=372_001,
    )

    cost = estimate_cost(
        usage,
        model,
        at=GPT_5_6_TERRA_LUNA_API_REDUCTION_AT,
    )

    assert cost is not None
    assert cost.ordinary_input_usd == pytest.approx(expected_ordinary)
    assert cost.cached_input_usd == pytest.approx(expected_cached)
    assert cost.cache_write_input_usd == pytest.approx(expected_cache_write)
    assert cost.output_usd == pytest.approx(expected_output)
    assert cost.total_usd == pytest.approx(expected_total)
```

- [ ] **Step 3: Update the pricing-table date assertion**

Change the existing date test to:

```python
def test_pricing_table_date_covers_terra_and_luna_reduction() -> None:
    assert pricing.PRICING_AS_OF == "2026-07-31"
```

- [ ] **Step 4: Run the new tests and confirm the old schedule fails them**

Run:

```bash
uv run pytest \
  tests/test_pricing.py::test_terra_and_luna_api_reduction_uses_exact_effective_boundary \
  tests/test_pricing.py::test_terra_and_luna_reduction_does_not_change_sol_or_codex_credit_rates \
  tests/test_pricing.py::test_terra_and_luna_reduced_short_context_costs \
  tests/test_pricing.py::test_terra_and_luna_reduced_long_context_costs \
  tests/test_pricing.py::test_pricing_table_date_covers_terra_and_luna_reduction -v
```

Expected: the boundary, reduced-cost, and pricing-date assertions fail because the current latest Terra and Luna rows still contain the June 26 rates and `PRICING_AS_OF` is still `2026-07-21`; the Sol and credit assertions pass.

- [ ] **Step 5: Append the reduced schedule rows without changing history**

In `src/codex_usage/pricing.py`, update the table date and add the named boundary:

```python
PRICING_AS_OF = "2026-07-31"
PRICING_METHOD = "effective_dated"
BASELINE_EFFECTIVE_FROM = datetime(1970, 1, 1, tzinfo=UTC)
GPT_5_6_API_EFFECTIVE_FROM = datetime(2026, 6, 26, tzinfo=UTC)
GPT_5_6_CREDIT_EFFECTIVE_FROM = datetime(2026, 7, 9, tzinfo=UTC)
GPT_5_6_TERRA_LUNA_API_REDUCTION_EFFECTIVE_FROM = datetime(
    2026,
    7,
    31,
    tzinfo=UTC,
)
```

Keep the existing June 26 Terra and Luna entries byte-for-byte, then append these two API schedule entries before the older-model entries:

```python
    _effective_rate(
        "gpt-5.6-terra",
        input_per_1m=2.00,
        cached_input_per_1m=0.20,
        output_per_1m=12.00,
        cache_write_input_per_1m=2.50,
        effective_from=GPT_5_6_TERRA_LUNA_API_REDUCTION_EFFECTIVE_FROM,
        request_pricing_contract=GPT_5_6_API_LONG_CONTEXT_PRICING,
    ),
    _effective_rate(
        "gpt-5.6-luna",
        input_per_1m=0.20,
        cached_input_per_1m=0.02,
        output_per_1m=1.20,
        cache_write_input_per_1m=0.25,
        effective_from=GPT_5_6_TERRA_LUNA_API_REDUCTION_EFFECTIVE_FROM,
        request_pricing_contract=GPT_5_6_API_LONG_CONTEXT_PRICING,
    ),
```

Do not modify `_schedule_entry_for_model`, `GPT_5_6_API_LONG_CONTEXT_PRICING`, or `CODEX_CREDIT_RATE_SCHEDULE`.

- [ ] **Step 6: Run the complete pricing suite**

Run:

```bash
uv run pytest tests/test_pricing.py -v
```

Expected: all pricing tests pass, including the June 26 historical-rate tests and the July 31 boundary tests.

- [ ] **Step 7: Check the patch and commit the pricing behavior**

Run:

```bash
git diff --check
git diff -- src/codex_usage/pricing.py tests/test_pricing.py
git add src/codex_usage/pricing.py tests/test_pricing.py
git commit -m "fix: update Terra and Luna API pricing"
```

Expected: one focused commit containing only the effective-dated pricing implementation and its regression tests.

---

### Task 2: Document The New Current Rates And Prepare Release 0.1.41

**Files:**
- Modify: `tests/test_task_transfer_docs.py`
- Modify: `tests/test_github_actions_workflow.py`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify mechanically: `uv.lock`
- Modify mechanically: `extensions/vscode/package.json`
- Modify mechanically: `extensions/vscode/package-lock.json`

**Interfaces:**
- Consumes: the Task 1 pricing boundary and values.
- Produces: matching `0.1.41` Python/extension release metadata and reader-facing current-rate documentation.
- Preserves: all changelog sections before `0.1.41` and all historical design/ADR files.

- [ ] **Step 1: Update documentation contract tests first**

In `tests/test_task_transfer_docs.py`:

1. Add `"0.1.41": "2026-07-30"` as the first item in `ROOT_RELEASE_DATES`.
2. Add `"0.1.41"` as the first item in `EXTENSION_RELEASE_VERSIONS`.
3. Replace the current cache-write and long-context prose assertions with:

```python
        assert (
            "standard cache-write rates per 1m tokens are: "
            "sol $6.25, terra $2.50, luna $0.25"
        ) in prose
        assert (
            "reduced terra and luna api rates apply from july 31, 2026; "
            "earlier usage keeps the original effective-dated rates"
        ) in prose
        assert (
            "sol ordinary input $10, cache read (cached input) $1, "
            "cache write $12.50, output $45"
        ) in prose
        assert (
            "terra ordinary input $4, cache read (cached input) $0.40, "
            "cache write $5, output $18"
        ) in prose
        assert (
            "luna ordinary input $0.40, cache read (cached input) $0.04, "
            "cache write $0.50, output $1.80"
        ) in prose
```

Keep the existing assertions for the 272,000-token boundary, credits, estimation disclaimer, and stale uncached-input wording.

Add a release-note contract test:

```python
@pytest.mark.parametrize(
    "changelog",
    (ROOT / "CHANGELOG.md", EXTENSION_ROOT / "CHANGELOG.md"),
    ids=("repository", "extension"),
)
def test_0_1_41_changelog_describes_effective_dated_price_reduction(
    changelog: Path,
) -> None:
    section = normalized_prose(
        markdown_section(
            changelog,
            "## 0.1.41 - 2026-07-30 - Reduced Terra And Luna API Pricing",
        )
    )

    assert "july 31, 2026" in section
    assert "historical" in section and "original rates" in section
    assert "sol" in section and "unchanged" in section
    assert "codex credit" in section and "unchanged" in section
```

- [ ] **Step 2: Update the release-metadata contract test**

In `tests/test_github_actions_workflow.py`, rename
`test_release_metadata_versions_are_0_1_40` to
`test_release_metadata_versions_are_0_1_41` and change all five expected
versions to `"0.1.41"`.

- [ ] **Step 3: Run the targeted tests and confirm they fail before the docs and version bump**

Run:

```bash
uv run pytest \
  tests/test_task_transfer_docs.py::test_current_docs_define_gpt_5_6_cache_write_pricing_contract \
  tests/test_task_transfer_docs.py::test_0_1_41_changelog_describes_effective_dated_price_reduction \
  tests/test_task_transfer_docs.py::test_changelogs_use_exact_historical_release_dates \
  tests/test_github_actions_workflow.py::test_release_metadata_versions_are_0_1_41 -v
```

Expected: failures identify the still-current old README prose, missing `0.1.41` changelog sections, missing release date/version entries, and `0.1.40` metadata.

- [ ] **Step 4: Update current pricing prose in both READMEs**

In `README.md` and `extensions/vscode/README.md`, preserve the checked-in/effective-dated and no-live-fetch explanation. Update the GPT-5.6 pricing paragraphs to say:

```markdown
The original Terra and Luna API rates apply through July 30, 2026. Reduced Terra and Luna API rates apply from July 31, 2026; earlier usage keeps the original effective-dated rates. GPT-5.6 Sol API pricing and all three models' Codex credit rates are unchanged.
```

Replace the current-rate sentence with:

```markdown
API-equivalent USD figures are estimates, not actual API or Codex billing. For GPT-5.6, standard cache-write rates per 1M tokens are: Sol $6.25, Terra $2.50, Luna $0.25; cache read (cached input) and ordinary input remain distinct categories. Exactly 272,000 input tokens is short-context pricing. More than 272,000 input tokens, including 272,001, prices the full retained request event at long-context API rates. Long-context rates per 1M tokens are: Sol ordinary input $10, cache read (cached input) $1, cache write $12.50, output $45; Terra ordinary input $4, cache read (cached input) $0.40, cache write $5, output $18; Luna ordinary input $0.40, cache read (cached input) $0.04, cache write $0.50, output $1.80. Codex credits do not use long-context or API cache-write categories; cache writes use the ordinary input credit rate.
```

Do not rewrite the June 26 or July 9 historical start-date statements and do not edit old changelog or design-document pricing values.

- [ ] **Step 5: Add matching 0.1.41 changelog entries**

Immediately after `## Unreleased` in both `CHANGELOG.md` and
`extensions/vscode/CHANGELOG.md`, add:

```markdown
## 0.1.41 - 2026-07-30 - Reduced Terra And Luna API Pricing

- Applied OpenAI's reduced Standard API rates for GPT-5.6 Terra and Luna from July 31, 2026.
- Preserved historical estimates by retaining the original rates for earlier usage.
- Kept GPT-5.6 Sol API pricing and Terra, Luna, and Sol Codex credit rates unchanged.
```

- [ ] **Step 6: Bump all release metadata mechanically**

Change `pyproject.toml` from `0.1.40` to `0.1.41`, then regenerate the Python lock metadata:

```bash
uv lock
```

From the extension directory, update both npm metadata files without creating a tag:

```bash
cd extensions/vscode
npm version 0.1.41 --no-git-tag-version
cd ../..
```

Expected changed metadata:

- `pyproject.toml`: project version `0.1.41`
- `uv.lock`: local `codex-usage` package version `0.1.41`
- `extensions/vscode/package.json`: version `0.1.41`
- `extensions/vscode/package-lock.json`: root and empty-package versions `0.1.41`

- [ ] **Step 7: Run the documentation and release contract tests**

Run:

```bash
uv run pytest tests/test_task_transfer_docs.py tests/test_github_actions_workflow.py -v
```

Expected: all documentation, dated changelog, workflow, and release metadata tests pass.

- [ ] **Step 8: Check the patch and commit the release preparation**

Run:

```bash
git diff --check
git diff -- \
  README.md \
  CHANGELOG.md \
  pyproject.toml \
  uv.lock \
  extensions/vscode/README.md \
  extensions/vscode/CHANGELOG.md \
  extensions/vscode/package.json \
  extensions/vscode/package-lock.json \
  tests/test_task_transfer_docs.py \
  tests/test_github_actions_workflow.py
git add \
  README.md \
  CHANGELOG.md \
  pyproject.toml \
  uv.lock \
  extensions/vscode/README.md \
  extensions/vscode/CHANGELOG.md \
  extensions/vscode/package.json \
  extensions/vscode/package-lock.json \
  tests/test_task_transfer_docs.py \
  tests/test_github_actions_workflow.py
git commit -m "chore: prepare 0.1.41 pricing release"
```

Expected: one focused commit containing documentation, changelogs, tests, and synchronized release metadata.

---

### Task 3: Verify The Complete Release Candidate

**Files:**
- Verify only; no tracked source changes expected.
- Generated ignored artifact: `output/releases/codex-usage-dashboard-darwin-arm64.vsix`
- Generated ignored native executable: `extensions/vscode/bin/darwin-arm64/codex-usage`

**Interfaces:**
- Consumes: the Task 1 pricing commit and Task 2 release-preparation commit.
- Produces: test and macOS Apple Silicon package evidence for the `0.1.41` release candidate.

- [ ] **Step 1: Run the complete Python suite**

Run:

```bash
uv run pytest
```

Expected: the complete Python test suite passes.

- [ ] **Step 2: Run the complete VS Code extension suite**

Run:

```bash
cd extensions/vscode
npm test
cd ../..
```

Expected: all extension tests pass.

- [ ] **Step 3: Build the macOS Apple Silicon VSIX**

Run:

```bash
cd extensions/vscode
npm run package:vsix:mac
cd ../..
```

Expected: the bundled Python executable builds, its CLI help check passes, the packaged version-3 Task Transfer smoke passes, and `output/releases/codex-usage-dashboard-darwin-arm64.vsix` is created.

- [ ] **Step 4: Inspect the package version, bundled executable, and architecture**

Run:

```bash
unzip -p \
  output/releases/codex-usage-dashboard-darwin-arm64.vsix \
  extension/package.json \
  | rg '"version": "0.1.41"'
unzip -l \
  output/releases/codex-usage-dashboard-darwin-arm64.vsix \
  | rg 'extension/bin/darwin-arm64/codex-usage$'
file extensions/vscode/bin/darwin-arm64/codex-usage
```

Expected:

- the packaged extension manifest contains `"version": "0.1.41"`;
- the VSIX contains `extension/bin/darwin-arm64/codex-usage`;
- `file` reports a Mach-O 64-bit arm64 executable.

- [ ] **Step 5: Confirm repository cleanliness and review the release commits**

Run:

```bash
git diff --check
git status --short
git log --oneline -3
```

Expected: no tracked changes remain after the two implementation commits. Ignored package/build outputs do not appear in `git status`.

- [ ] **Step 6: Record verification evidence for integration**

Report:

- complete Python test count and result;
- complete extension test count and result;
- macOS VSIX path and packaged `0.1.41` version;
- packaged Task Transfer smoke result;
- Mach-O arm64 architecture result;
- the two implementation commit hashes.

Do not tag, push, or trigger the release workflow in this task. Integration and publication are separate explicit operations after review.
