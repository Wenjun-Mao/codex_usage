# Model Pricing Hardening And Screenshot Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Codex Usage Dashboard safe for future model launches such as GPT-5.6, while refreshing the public README/Marketplace screenshot to the current dashboard UI.

**Architecture:** Keep parsing and aggregation model-agnostic. Tighten pricing lookup so only exact checked-in model IDs or explicit aliases receive API USD and Codex credit rates; unknown future models remain visible in totals and model mix but are clearly marked unpriced until official rates are added. Generate the screenshot from synthetic data using the existing HTML/SVG report renderer, not real user logs.

**Tech Stack:** Python 3.13, `uv`, pytest, TypeScript/VS Code wrapper, existing native HTML/CSS/SVG report renderer, Windows Edge headless screenshot for the synthetic Marketplace image.

---

## File Structure

- Modify `src/codex_usage/pricing.py`: own canonical model-rate lookup and effective-dated schedules.
- Modify `tests/test_pricing.py`: assert exact/alias matching and future-model unpriced behavior.
- Modify `tests/test_parser_aggregation.py`: assert unknown future models remain visible and unpriced in aggregation.
- Modify `tests/test_reporting_html.py`: assert future unpriced models produce clear HTML warnings.
- Modify `docs/adr/0003-effective-dated-pricing.md`: record the canonical matching guardrail.
- Modify `README.md`: update pricing caveat and keep screenshot reference.
- Modify `extensions/vscode/README.md`: update Marketplace-facing pricing caveat.
- Modify `CHANGELOG.md` and `extensions/vscode/CHANGELOG.md`: add release note.
- Modify `pyproject.toml`, `uv.lock`, `extensions/vscode/package.json`, and `extensions/vscode/package-lock.json`: bump patch version.
- Replace `docs/marketplace/dashboard-synthetic.png`: synthetic dashboard screenshot generated from current report UI.

---

### Task 1: Pricing Lookup Tests

**Files:**
- Modify: `tests/test_pricing.py`
- Test: `tests/test_pricing.py`

- [ ] **Step 1: Add exact-match and alias tests**

Append these tests to `tests/test_pricing.py`:

```python
def test_rate_lookup_requires_exact_model_or_explicit_alias(monkeypatch) -> None:
    base_rate = ModelRate(input_per_1m=1.0, cached_input_per_1m=0.1, output_per_1m=2.0)
    schedule = (
        EffectiveModelRate(
            model_key="gpt-5.6",
            effective_from=datetime(1970, 1, 1, tzinfo=UTC),
            rate=base_rate,
            aliases=("gpt-5.6-2026-08-18",),
        ),
    )
    monkeypatch.setattr(pricing, "API_PRICING_USD_SCHEDULE", schedule)

    assert rate_for_model("gpt-5.6") == base_rate
    assert rate_for_model("GPT-5.6") == base_rate
    assert rate_for_model("gpt-5.6-2026-08-18") == base_rate
    assert rate_for_model("gpt-5.6-pro") is None
    assert rate_for_model("gpt-5.6-mini") is None
    assert rate_for_model("wrapper-gpt-5.6") is None


def test_future_model_without_checked_in_rate_is_unpriced() -> None:
    usage = TokenUsage(input_tokens=1_000, cached_input_tokens=100, output_tokens=50, total_tokens=1_050)

    assert rate_for_model("gpt-5.6") is None
    assert credit_rate_for_model("gpt-5.6") is None
    assert estimate_cost(usage, "gpt-5.6") is None
    assert estimate_codex_credits(usage, "gpt-5.6") is None
```

- [ ] **Step 2: Run the focused tests and confirm they fail before implementation**

Run:

```powershell
uv run pytest tests/test_pricing.py -q
```

Expected before implementation:

```text
FAILED tests/test_pricing.py::test_rate_lookup_requires_exact_model_or_explicit_alias
```

The likely failure is `TypeError: EffectiveModelRate.__init__() got an unexpected keyword argument 'aliases'`.

---

### Task 2: Canonical Model Matching

**Files:**
- Modify: `src/codex_usage/pricing.py`
- Test: `tests/test_pricing.py`

- [ ] **Step 1: Add aliases to `EffectiveModelRate`**

In `src/codex_usage/pricing.py`, change the dataclass from:

```python
@dataclass(frozen=True)
class EffectiveModelRate:
    model_key: str
    effective_from: datetime
    rate: ModelRate
```

to:

```python
@dataclass(frozen=True)
class EffectiveModelRate:
    model_key: str
    effective_from: datetime
    rate: ModelRate
    aliases: tuple[str, ...] = ()
```

- [ ] **Step 2: Let `_effective_rate` accept aliases**

Change `_effective_rate` to:

```python
def _effective_rate(
    model_key: str,
    *,
    input_per_1m: float,
    cached_input_per_1m: float,
    output_per_1m: float,
    effective_from: datetime = BASELINE_EFFECTIVE_FROM,
    aliases: tuple[str, ...] = (),
) -> EffectiveModelRate:
    return EffectiveModelRate(
        model_key=model_key,
        effective_from=effective_from,
        rate=ModelRate(
            input_per_1m=input_per_1m,
            cached_input_per_1m=cached_input_per_1m,
            output_per_1m=output_per_1m,
        ),
        aliases=aliases,
    )
```

- [ ] **Step 3: Replace substring lookup with exact canonical lookup**

Replace `_rate_for_model` in `src/codex_usage/pricing.py` with:

```python
def _rate_for_model(
    schedule: tuple[EffectiveModelRate, ...],
    model: str,
    at: datetime | None = None,
) -> ModelRate | None:
    normalized = _normalize_model_id(model)
    if not normalized:
        return None
    effective_at = _normalize_effective_at(at)
    candidates = [
        entry
        for entry in schedule
        if _matches_model(entry, normalized)
        and (effective_at is None or _normalize_effective_at(entry.effective_from) <= effective_at)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda entry: _normalize_effective_at(entry.effective_from) or BASELINE_EFFECTIVE_FROM,
    ).rate
```

Add these helpers above `_normalize_effective_at`:

```python
def _matches_model(entry: EffectiveModelRate, normalized_model: str) -> bool:
    return normalized_model in {_normalize_model_id(entry.model_key), *(_normalize_model_id(alias) for alias in entry.aliases)}


def _normalize_model_id(value: str) -> str:
    return value.strip().casefold()
```

- [ ] **Step 4: Run pricing tests**

Run:

```powershell
uv run pytest tests/test_pricing.py -q
```

Expected:

```text
passed
```

---

### Task 3: Aggregation And Report Regressions For Future Models

**Files:**
- Modify: `tests/test_parser_aggregation.py`
- Modify: `tests/test_reporting_html.py`
- Test: `tests/test_parser_aggregation.py`, `tests/test_reporting_html.py`

- [ ] **Step 1: Add an aggregation test for an unknown future model**

Append this test to `tests/test_parser_aggregation.py`:

```python
def test_unknown_future_model_is_grouped_but_unpriced(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    _write_jsonl(
        path,
        [
            _session_meta(session_id="session", cwd=str(tmp_path)),
            _turn_context(model="gpt-5.6"),
            _token_count(
                total={"input_tokens": 1_000, "cached_input_tokens": 100, "output_tokens": 50, "total_tokens": 1_050}
            ),
        ],
    )

    records = parse_session_file(path)
    total = summarize_records(records)
    rows = aggregate_records(records, "model", UTC)

    assert rows[0].key == "gpt-5.6"
    assert rows[0].usage.total_tokens == 1_050
    assert rows[0].cost.unpriced_tokens == 1_050
    assert rows[0].credits.unpriced_tokens == 1_050
    assert total.cost.unpriced_tokens == 1_050
    assert total.credits.unpriced_tokens == 1_050
```

Use the existing helper names in that file. If `_token_count` requires keyword names that differ, adapt only the call shape to the existing helper signature.

- [ ] **Step 2: Add an HTML warning test for an unknown future model**

Append this test to `tests/test_reporting_html.py`:

```python
def test_html_report_warns_for_unknown_future_model_without_price_data(tmp_path: Path) -> None:
    total = UsageSummary(
        usage=TokenUsage(input_tokens=1_000, cached_input_tokens=100, output_tokens=50, total_tokens=1_050),
        cost=CostBreakdown(unpriced_tokens=1_050),
        credits=CreditBreakdown(unpriced_tokens=1_050),
        record_count=1,
    )
    future_model_row = _row("gpt-5.6", "gpt-5.6", 1_050, unpriced=1_050, credit_unpriced=1_050)
    output_path = tmp_path / "report.html"

    render_html_report(
        output_path=output_path,
        generated_at=datetime(2026, 6, 25, tzinfo=UTC),
        range_name="7d",
        total=total,
        daily_rows=[_row("2026-06-25", "2026-06-25", 1_050, unpriced=1_050, credit_unpriced=1_050)],
        hourly_rows=[_row("2026-06-25 10:00", "2026-06-25 10:00", 1_050, unpriced=1_050, credit_unpriced=1_050)],
        project_rows=[_row("repo", "demo", 1_050, unpriced=1_050, credit_unpriced=1_050)],
        model_rows=[future_model_row],
        sessions_dirs=[tmp_path],
        files_scanned=1,
        theme="day",
    )

    html = output_path.read_text(encoding="utf-8")
    assert "gpt-5.6" in html
    assert "No price data is available for 1,050 tokens" in html
    assert "API USD excludes 1,050 tokens from models without API USD rates" in html
```

- [ ] **Step 3: Run focused tests**

Run:

```powershell
uv run pytest tests/test_parser_aggregation.py tests/test_reporting_html.py -q
```

Expected:

```text
passed
```

---

### Task 4: Pricing Contract Documentation

**Files:**
- Modify: `docs/adr/0003-effective-dated-pricing.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`

- [ ] **Step 1: Update ADR 0003 guardrails**

In `docs/adr/0003-effective-dated-pricing.md`, replace the `## Guardrails` body with:

```markdown
Keep API USD and Codex credits separate. Do not fetch pricing over the network in normal reporting.

Model matching is exact by checked-in model id or explicit alias. Do not price an unknown future variant such as `gpt-5.6-pro` by substring-matching a base model such as `gpt-5.6`; leave it visible but unpriced until official rates are checked in.
```

- [ ] **Step 2: Update root README pricing caveat**

In `README.md`, replace the paragraph beginning with `The tool does not fetch live pricing.` with:

```markdown
The tool does not fetch live pricing. Cost and credit values are estimates based on the checked-in pricing table version shown in each report. New Codex models may appear in local logs before this repository has official checked-in rates for them; those models remain visible in totals and model mix, but their API USD and Codex credit estimates are excluded until a patch release adds exact effective-dated rates.
```

- [ ] **Step 3: Update VS Code README pricing caveat**

In `extensions/vscode/README.md`, replace the paragraph beginning with `API-equivalent USD and Codex credit estimates are calculated` with:

```markdown
API-equivalent USD and Codex credit estimates are calculated from checked-in effective-dated pricing tables. The extension does not fetch live pricing, does not know your subscription price, and does not convert Codex credits to dollars. If a newly released Codex model appears before checked-in rates are added, the dashboard keeps its tokens visible and marks cost/credits as partial rather than guessing from another model.
```

---

### Task 5: Version And Changelog

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`

- [ ] **Step 1: Bump Python package version**

In `pyproject.toml`, change:

```toml
version = "0.1.29"
```

to:

```toml
version = "0.1.30"
```

- [ ] **Step 2: Refresh `uv.lock`**

Run:

```powershell
uv lock
```

Expected:

```text
Resolved ... packages
```

- [ ] **Step 3: Bump VS Code extension version**

In `extensions/vscode/package.json`, change:

```json
"version": "0.1.29"
```

to:

```json
"version": "0.1.30"
```

- [ ] **Step 4: Refresh `package-lock.json`**

Run:

```powershell
Push-Location extensions\vscode
npm install --package-lock-only
Pop-Location
```

Expected:

```text
up to date
```

- [ ] **Step 5: Add changelog notes**

Add this section near the top of `CHANGELOG.md`:

```markdown
## 0.1.30 - Future Model Pricing Hardening

- Hardened checked-in pricing lookup so unknown future model variants remain visible but unpriced instead of inheriting rates by substring.
- Documented the exact-model pricing guardrail for future model launches such as GPT-5.6.
- Refreshed the synthetic dashboard screenshot used in README and Marketplace materials.
```

Add this section near the top of `extensions/vscode/CHANGELOG.md`:

```markdown
## 0.1.30

- Hardened future-model pricing behavior so newly released Codex models show usage immediately while cost estimates stay partial until official rates are checked in.
- Refreshed the synthetic dashboard screenshot.
```

---

### Task 6: Synthetic Screenshot Refresh

**Files:**
- Replace: `docs/marketplace/dashboard-synthetic.png`
- Optional generated file: `output/marketplace-dashboard-synthetic.html`

- [ ] **Step 1: Generate a synthetic report HTML**

Run this from the repository root:

```powershell
@'
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import AggregateRow, UsageSummary
from codex_usage.models import TokenUsage
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.reporting import render_html_report


def row(key, label, total, input_tokens, cached, output, cost, credits):
    return AggregateRow(
        key=key,
        label=label,
        usage=TokenUsage(
            input_tokens=input_tokens,
            cached_input_tokens=cached,
            output_tokens=output,
            total_tokens=total,
        ),
        cost=CostBreakdown(total_usd=cost),
        credits=CreditBreakdown(total_credits=credits),
        record_count=12,
    )


daily = [
    row("2026-06-01", "06/01", 1_250_000, 1_210_000, 980_000, 40_000, 0.82, 20.4),
    row("2026-06-02", "06/02", 1_880_000, 1_820_000, 1_520_000, 60_000, 1.21, 31.2),
    row("2026-06-03", "06/03", 2_430_000, 2_360_000, 2_000_000, 70_000, 1.66, 42.0),
    row("2026-06-04", "06/04", 3_900_000, 3_760_000, 3_180_000, 140_000, 2.48, 66.3),
    row("2026-06-05", "06/05", 4_820_000, 4_650_000, 3_950_000, 170_000, 3.08, 82.8),
    row("2026-06-06", "06/06", 5_650_000, 5_430_000, 4_680_000, 220_000, 3.64, 95.7),
    row("2026-06-07", "06/07", 6_200_000, 5_960_000, 5_120_000, 240_000, 4.02, 106.5),
]
hourly = [
    row("2026-06-05 09:00", "2026-06-05 09:00", 580_000, 560_000, 470_000, 20_000, 0.38, 9.7),
    row("2026-06-05 14:00", "2026-06-05 14:00", 1_100_000, 1_060_000, 890_000, 40_000, 0.72, 18.9),
    row("2026-06-06 11:00", "2026-06-06 11:00", 1_480_000, 1_420_000, 1_180_000, 60_000, 0.96, 25.3),
    row("2026-06-06 16:00", "2026-06-06 16:00", 1_950_000, 1_870_000, 1_560_000, 80_000, 1.26, 33.5),
    row("2026-06-07 10:00", "2026-06-07 10:00", 2_260_000, 2_180_000, 1_850_000, 80_000, 1.47, 38.7),
    row("2026-06-07 15:00", "2026-06-07 15:00", 2_620_000, 2_520_000, 2_140_000, 100_000, 1.70, 44.1),
]
projects = [
    row("https://github.com/example/usage-lab", "usage-lab", 8_200_000, 7_950_000, 6_700_000, 250_000, 5.41, 142.3),
    row("https://github.com/example/docs-sandbox", "docs-sandbox", 6_100_000, 5_900_000, 4_950_000, 200_000, 4.08, 106.7),
    row("https://github.com/example/analytics-demo", "analytics-demo", 4_300_000, 4_120_000, 3_500_000, 180_000, 2.93, 76.8),
]
models = [
    row("gpt-5.5", "gpt-5.5", 10_800_000, 10_400_000, 8_900_000, 400_000, 7.24, 185.0),
    row("gpt-5.4", "gpt-5.4", 5_900_000, 5_700_000, 4_850_000, 200_000, 3.82, 99.4),
    row("gpt-5.4-mini", "gpt-5.4-mini", 1_900_000, 1_820_000, 1_500_000, 80_000, 0.72, 22.1),
]
total = UsageSummary(
    usage=TokenUsage(input_tokens=17_920_000, cached_input_tokens=15_250_000, output_tokens=680_000, total_tokens=18_600_000),
    cost=CostBreakdown(total_usd=11.78),
    credits=CreditBreakdown(total_credits=306.5),
    record_count=426,
)

render_html_report(
    output_path=Path("output/marketplace-dashboard-synthetic.html"),
    generated_at=datetime(2026, 6, 25, 12, 0, tzinfo=UTC),
    range_name="7d",
    total=total,
    daily_rows=daily,
    hourly_rows=hourly,
    project_rows=projects,
    model_rows=models,
    sessions_dirs=[Path("Synthetic Codex sessions")],
    files_scanned=42,
    storage_roots=["Synthetic local data"],
    theme="day",
)
'@ | uv run python -
```

Expected:

```text
output/marketplace-dashboard-synthetic.html exists
```

- [ ] **Step 2: Capture the screenshot with Edge headless**

Run:

```powershell
$edgeCandidates = @(
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$edge = $edgeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge was not found. Open output/marketplace-dashboard-synthetic.html manually and capture docs/marketplace/dashboard-synthetic.png." }
$htmlPath = (Resolve-Path output\marketplace-dashboard-synthetic.html).Path.Replace("\", "/")
& $edge --headless --disable-gpu --window-size=1440,900 --screenshot="$PWD\docs\marketplace\dashboard-synthetic.png" "file:///$htmlPath"
```

Expected:

```text
docs/marketplace/dashboard-synthetic.png is replaced
```

- [ ] **Step 3: Verify the screenshot is synthetic and readable**

Open `docs/marketplace/dashboard-synthetic.png` and confirm:

```text
The screenshot contains no real file paths, no real project names, no personal usernames, and no raw Codex logs.
```

---

### Task 7: Full Verification And Packaging

**Files:**
- No new files unless package output changes under `output/`

- [ ] **Step 1: Run Python tests**

Run:

```powershell
uv run pytest
```

Expected:

```text
passed
```

- [ ] **Step 2: Run VS Code extension tests**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

```text
node --test test/*.test.js
... pass ...
```

- [ ] **Step 3: Rebuild the Windows VSIX**

Run:

```powershell
Push-Location extensions\vscode
npm run package:vsix:win
Pop-Location
```

Expected:

```text
DONE  Packaged: D:\MyDocuments\03-PythonProjects\utility_projects\codex_usage\output\codex-usage-dashboard-win32-x64.vsix
```

- [ ] **Step 4: Inspect public-safe changed files**

Run:

```powershell
git status --short
git diff -- README.md extensions\vscode\README.md docs\adr\0003-effective-dated-pricing.md CHANGELOG.md extensions\vscode\CHANGELOG.md
```

Expected:

```text
Only pricing hardening docs, version files, tests, and the synthetic screenshot are changed.
No real Codex JSONL logs, personal screenshots, credentials, or generated reports are staged.
```

- [ ] **Step 5: Commit when approved**

Only after review, run:

```powershell
git add src\codex_usage\pricing.py tests\test_pricing.py tests\test_parser_aggregation.py tests\test_reporting_html.py docs\adr\0003-effective-dated-pricing.md README.md extensions\vscode\README.md CHANGELOG.md extensions\vscode\CHANGELOG.md pyproject.toml uv.lock extensions\vscode\package.json extensions\vscode\package-lock.json docs\marketplace\dashboard-synthetic.png
git commit -m "chore: harden future model pricing"
```

Expected:

```text
[main ...] chore: harden future model pricing
```

---

## Self-Review

- Spec coverage: pricing hardening, future model behavior, docs caveat, screenshot refresh, version bump, tests, and package rebuild are all covered.
- Placeholder scan: no implementation step says TBD/TODO/fill later. The only adaptive note is constrained to matching existing helper call signatures in `tests/test_parser_aggregation.py`.
- Type consistency: `EffectiveModelRate.aliases`, `_matches_model`, and `_normalize_model_id` are introduced before use. Existing constructor calls remain valid because `aliases` has a default.
