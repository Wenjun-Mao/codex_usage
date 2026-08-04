# Project Role And Model Breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an accessible per-project token breakdown that separates root tasks from structured subagents and then separates each role by model, while reusing range-filtered cached records and featuring the result in the repository and Marketplace documentation.

**Architecture:** Persist an explicit `usage_role` on every usage record in disposable cache schema 5, then build one project-role-model cube from the records already loaded for the selected range. Convert that cube into presentation-only points with one shared top-seven-plus-Other palette, render two adjacent role groups per project, and reuse the same visual model identities in Model Mix. Keep daily/hourly aggregation and exact Model Details unchanged.

**Tech Stack:** Python 3.13 dataclasses and `Literal`, SQLite, pytest, native HTML/CSS, TypeScript/Node tests, Python Playwright with Chromium, Pillow, uv, npm, PyInstaller, VSIX packaging.

## Global Constraints

- `UsageRecord.usage_role` is required and accepts exactly `root` or `subagent`.
- A session is `subagent` only when metadata contains a structured `payload.source.subagent` object; a parent task id is neither required nor sufficient.
- Cache schema 5 is disposable derived data. Schema 4 is deleted and rebuilt from source; do not add migration, dual-read, or compatibility branches.
- Build the project-role-model cube in one pass over records already filtered by range and selected projects. Do not reopen JSONL files or issue another cache inventory/query.
- Select the seven largest exact models report-wide by descending total tokens and model id as the tie-breaker. Combine the remaining exact models into visual-only `Other`.
- Project Breakdown and Model Mix use the same visual model order and colors. `Other` always uses the neutral eighth color. Model Details remains exact and ungrouped.
- Keep one absolute-scale row per project, the existing top-twelve chart limit, and an 8 px neutral role gap only when both roles have positive usage.
- Preserve every token category, effective-dated API cost field, Codex credit field, unpriced-token field, and event count through role/model aggregation.
- Keep reports free of runtime JavaScript, remote assets, and third-party chart frameworks.
- Keep changed Python and TypeScript files below 500 lines; split report CSS and table rendering into focused modules before they cross that guardrail.
- Keep Windows x64 and macOS Apple Silicon as the only packaged targets. Linux, Intel macOS, and Windows ARM64 remain unsupported.
- Regenerate `docs/marketplace/dashboard-synthetic.png` with `uv run python scripts/generate_marketplace_screenshot.py`; validate it with the same command plus `--check`.

---

### Task 1: Explicit Usage Role And Disposable Cache Schema 5

**Files:**
- Modify: `src/codex_usage/models.py:1-142`
- Modify: `src/codex_usage/parser.py:85-204`
- Modify: `src/codex_usage/session_cache.py:35-81`
- Modify: `src/codex_usage/session_cache_schema.py:1-231`
- Modify: `src/codex_usage/session_cache_generations.py:139-181`
- Modify: `src/codex_usage/session_cache_queries.py:51-76`
- Modify: `extensions/vscode/src/core.ts:124-134`
- Modify: `extensions/vscode/src/dashboardRefresh.ts:1-122`
- Modify: `tests/test_session_provenance.py`
- Rename: `tests/test_session_cache_schema_v4.py` -> `tests/test_session_cache_schema_v5.py`
- Modify: `tests/test_session_cache.py`
- Modify: `tests/test_range_cache_queries.py:250-318`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_parser_aggregation.py`
- Modify: `tests/test_project_transition_detection.py`
- Modify: `tests/test_project_transitions.py`
- Modify: `extensions/vscode/test/core.test.js`
- Modify: `extensions/vscode/test/dashboardRefresh.test.js`
- Modify: `extensions/vscode/test/syncProcess.test.js`

**Interfaces:**
- Produces: `UsageRole = Literal["root", "subagent"]`.
- Produces: `ROOT_USAGE_ROLE`, `SUBAGENT_USAGE_ROLE`, `usage_role_from_is_subagent(bool) -> UsageRole`, and `parse_usage_role(object) -> UsageRole` in `models.py`.
- Produces: required `UsageRecord.usage_role: UsageRole`, included in `UsageRecord.to_dict()`.
- Produces: `CACHE_SCHEMA_VERSION = 5`, `PARSER_CACHE_VERSION = 4`, `CACHE_DB_NAME = "usage-cache-v5.sqlite3"`, and legacy cleanup for both schema-4 and unversioned database files.
- Produces: `legacyCacheDbPaths(globalStoragePath: string): string[]` for extension loading-state detection.
- Consumes: the existing `SessionMetadata.is_subagent` classification from `session_provenance.py`.

- [ ] **Step 1: Add failing parser role tests**

Extend `tests/test_session_provenance.py` so ordinary metadata, a user-visible fork, malformed source metadata, a spawned child, and a parentless review all produce explicit usage roles:

```python
from codex_usage.models import ROOT_USAGE_ROLE, SUBAGENT_USAGE_ROLE


def test_usage_records_keep_explicit_root_and_parentless_subagent_roles(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "root.jsonl"
    malformed_path = tmp_path / "malformed.jsonl"
    review_path = tmp_path / "review.jsonl"
    _write_session(root_path, "cli")
    _write_session(malformed_path, {"subagent": "review"})
    _write_session(review_path, {"subagent": {"other": "review"}})

    root = parse_session_file(root_path)
    malformed = parse_session_file(malformed_path)
    review = parse_session_file(review_path)

    assert [record.usage_role for record in root] == [ROOT_USAGE_ROLE]
    assert [record.usage_role for record in malformed] == [ROOT_USAGE_ROLE]
    assert [record.usage_role for record in review] == [SUBAGENT_USAGE_ROLE]
    assert review[0].parent_thread_id == ""
```

Also extend the existing spawned-parent parser test in `tests/test_parser_aggregation.py` with:

```python
assert child_record.usage_role == SUBAGENT_USAGE_ROLE
```

Extend `test_parser_ignores_imported_parent_usage_in_forked_session_file()` in the same module with:

```python
assert {record.usage_role for record in records} == {ROOT_USAGE_ROLE}
```

- [ ] **Step 2: Add failing schema-5 and range round-trip tests**

Rename the schema test file and replace its schema-3 fixture with a minimal schema-4 database. Assert the old sentinel is discarded and the resulting database is schema 5:

```python
def test_schema_four_is_discarded_instead_of_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / CACHE_DB_NAME
    create_schema_four_database(db_path, sentinel_total_tokens=999)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        state = cache_schema._ensure_schema(connection)

    assert state.reset is True
    assert state.reset_reason == "schema 4"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from usage_records").fetchone()[0] == 0
        assert connection.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone()[0] == "5"
        columns = {
            row[1]: row for row in connection.execute("pragma table_info(usage_records)")
        }
    assert columns["usage_role"][3] == 1
```

Add a contract-corruption test by enabling `pragma ignore_check_constraints`, inserting `usage_role = 'worker'`, and asserting the next `_ensure_schema()` resets the cache. Add cache and range assertions proving a parentless structured subagent is restored as `subagent` and an ordinary record as `root`.

Update the hand-built `usage_records` table and insert statement in `tests/test_range_cache_queries.py` to include a non-null `usage_role` column before token fields:

```sql
usage_role text not null check (usage_role in ('root', 'subagent'))
```

Pass `"root"` or `"subagent"` explicitly in every hand-built row.

- [ ] **Step 3: Add failing extension cache-path tests**

Update `extensions/vscode/test/core.test.js` to require the new path contract:

```javascript
assert.equal(
  cacheDbPath("C:/global-storage"),
  path.join("C:/global-storage", "cache", "usage-cache-v5.sqlite3"),
);
assert.deepEqual(legacyCacheDbPaths("C:/global-storage"), [
  path.join("C:/global-storage", "cache", "usage-cache-v4.sqlite3"),
  path.join("C:/global-storage", "cache", "usage-cache.sqlite3"),
]);
```

In `dashboardRefresh.test.js`, create only `usage-cache-v4.sqlite3` and assert `dashboardLoadingKind()` returns `"rebuilding"`. Update the existing unversioned legacy case to use `legacyCacheDbPaths(globalStoragePath)[1]`. Update `syncProcess.test.js` to use the exported list rather than a single legacy path.

- [ ] **Step 4: Run the new tests to verify the contract is missing**

Run:

```bash
uv run pytest -q tests/test_session_provenance.py tests/test_parser_aggregation.py tests/test_session_cache_schema_v5.py tests/test_session_cache.py tests/test_range_cache_queries.py
npm --prefix extensions/vscode run build
node --test --test-name-pattern="cache|loading" extensions/vscode/test/core.test.js extensions/vscode/test/dashboardRefresh.test.js
```

Expected: Python fails because `UsageRecord` has no role and schema 5 does not exist; Node fails because the extension still points at `usage-cache-v4.sqlite3` and exports one legacy path.

- [ ] **Step 5: Add the domain role contract and parser assignment**

Add the following definitions above `UsageRecord` in `models.py`:

```python
from typing import Any, Literal

type UsageRole = Literal["root", "subagent"]
ROOT_USAGE_ROLE: UsageRole = "root"
SUBAGENT_USAGE_ROLE: UsageRole = "subagent"


def usage_role_from_is_subagent(is_subagent: bool) -> UsageRole:
    return SUBAGENT_USAGE_ROLE if is_subagent else ROOT_USAGE_ROLE


def parse_usage_role(value: object) -> UsageRole:
    if value == ROOT_USAGE_ROLE:
        return ROOT_USAGE_ROLE
    if value == SUBAGENT_USAGE_ROLE:
        return SUBAGENT_USAGE_ROLE
    raise ValueError(f"unsupported usage role: {value!r}")
```

Place the required field before defaulted fields in `UsageRecord`:

```python
@dataclass(frozen=True)
class UsageRecord:
    timestamp: datetime
    usage: TokenUsage
    session_id: str
    file_path: Path
    usage_role: UsageRole
    model: str = UNKNOWN
```

Include `"usage_role": self.usage_role` in `to_dict()`. In `parser.py`, set:

```python
usage_role=usage_role_from_is_subagent(metadata.is_subagent),
```

on every emitted record. Add `usage_role=ROOT_USAGE_ROLE` to direct test constructors in `test_cli.py`, `test_parser_aggregation.py`, `test_project_transition_detection.py`, and `test_project_transitions.py` so all callers honor the required contract.

- [ ] **Step 6: Implement schema-5 persistence and invalid-role rebuilding**

Set the schema/parser versions and add the constrained column after `parent_thread_id`:

```python
CACHE_SCHEMA_VERSION = 5
PARSER_CACHE_VERSION = 4

# usage_records schema
usage_role text not null check (usage_role in ('root', 'subagent')),
```

After checking version metadata in `_schema_matches`, reject missing/invalid stored role values. Keep the role query inside a `try` so a malformed table also returns `False` and takes the normal reset path:

```python
if not all(metadata.get(key) == value for key, value in expected_versions.items()):
    return False
try:
    invalid_role = connection.execute(
        """
        select 1 from usage_records
        where usage_role is null or usage_role not in ('root', 'subagent')
        limit 1
        """
    ).fetchone()
except sqlite3.Error:
    return False
return invalid_role is None
```

Persist and restore the field in the existing statement order:

```python
# session_cache_generations.py
insert into usage_records (
    file_key, file_path, record_index, timestamp, timestamp_us,
    session_id, turn_id, model, effort, collaboration_mode,
    project_key, project_label, project_aliases_json, cwd,
    git_repository_url, git_branch, parent_thread_id, usage_role,
    input_tokens, cached_input_tokens, cache_write_input_tokens,
    output_tokens, reasoning_output_tokens, total_tokens
) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

values = (
    entry.file_key,
    str(entry.path),
    index,
    record.timestamp.isoformat(),
    _timestamp_us(record.timestamp),
    record.session_id,
    record.turn_id,
    record.model,
    record.effort,
    record.collaboration_mode,
    record.project_key,
    record.project_label,
    json.dumps(list(record.project_aliases)),
    record.cwd,
    record.git_repository_url,
    record.git_branch,
    record.parent_thread_id,
    record.usage_role,
    usage.input_tokens,
    usage.cached_input_tokens,
    usage.cache_write_input_tokens,
    usage.output_tokens,
    usage.reasoning_output_tokens,
    usage.total_tokens,
)

# session_cache_queries.py
usage_role=parse_usage_role(row["usage_role"]),
```

Use a new database filename and clean both previous filenames:

```python
CACHE_DB_NAME = "usage-cache-v5.sqlite3"
LEGACY_CACHE_DB_NAMES = ("usage-cache-v4.sqlite3", "usage-cache.sqlite3")
```

Update `tests/test_session_cache.py` to assert both legacy databases and their `-wal`/`-shm` siblings are removed only after schema 5 opens successfully.

- [ ] **Step 7: Update extension loading-state detection**

Replace the singular legacy helper in `core.ts`:

```typescript
export function cacheDbPath(globalStoragePath: string): string {
  return path.join(cacheDirPath(globalStoragePath), "usage-cache-v5.sqlite3");
}

export function legacyCacheDbPaths(globalStoragePath: string): string[] {
  return ["usage-cache-v4.sqlite3", "usage-cache.sqlite3"].map((name) =>
    path.join(cacheDirPath(globalStoragePath), name),
  );
}
```

Make `dashboardLoadingKind()` classify either prior database as a rebuild:

```typescript
if (await pathExists(cacheDbPath(globalStoragePath))) {
  return "refreshing";
}
for (const legacyPath of legacyCacheDbPaths(globalStoragePath)) {
  if (await pathExists(legacyPath)) {
    return "rebuilding";
  }
}
return "initializing";
```

- [ ] **Step 8: Run role, cache, range, extension, and equivalence tests**

Run:

```bash
uv run pytest -q tests/test_session_provenance.py tests/test_parser_aggregation.py tests/test_session_cache_schema_v5.py tests/test_session_cache.py tests/test_range_cache_queries.py tests/test_parallel_cache_equivalence.py tests/test_parallel_report_equivalence.py
npm --prefix extensions/vscode test
```

Expected: all selected Python tests and the complete extension suite pass. Cached and direct parsing produce the same `usage_role` values.

- [ ] **Step 9: Commit the explicit role/cache contract**

```bash
git add src/codex_usage/models.py src/codex_usage/parser.py src/codex_usage/session_cache.py src/codex_usage/session_cache_schema.py src/codex_usage/session_cache_generations.py src/codex_usage/session_cache_queries.py extensions/vscode/src/core.ts extensions/vscode/src/dashboardRefresh.ts tests/test_session_provenance.py tests/test_session_cache_schema_v4.py tests/test_session_cache_schema_v5.py tests/test_session_cache.py tests/test_range_cache_queries.py tests/test_cli.py tests/test_parser_aggregation.py tests/test_project_transition_detection.py tests/test_project_transitions.py extensions/vscode/test/core.test.js extensions/vscode/test/dashboardRefresh.test.js extensions/vscode/test/syncProcess.test.js
git commit -m "feat: persist explicit usage roles"
```

---

### Task 2: One-Pass Project-Role-Model Aggregation

**Files:**
- Create: `src/codex_usage/report_breakdown.py`
- Create: `tests/test_report_breakdown.py`
- Modify: `src/codex_usage/aggregation.py:27-60,151-213`

**Interfaces:**
- Consumes: `UsageRecord.usage_role`, `UsageRole`, `AggregateRow`, and effective-dated record pricing.
- Produces: `UsageSummary.add(other: UsageSummary) -> UsageSummary` and `summarize_record(record: UsageRecord) -> UsageSummary`.
- Produces: `VisualModelBucket`, `RoleModelBreakdown`, `ProjectRoleModelBreakdown`, and `ReportBreakdown` frozen dataclasses.
- Produces: `build_report_breakdown(records: list[UsageRecord], *, visual_model_limit: int = 7) -> ReportBreakdown`.
- Produces: `OTHER_MODEL_KEY = "__codex_usage_other_models__"` and `OTHER_MODEL_LABEL = "Other"`.

- [ ] **Step 1: Write failing cube and conservation tests**

Create `tests/test_report_breakdown.py` with a `_record()` helper that always supplies project, role, model, timestamp, and all token fields. The primary test should use:

```python
records = [
    _record("alpha", "Alpha", "root", "gpt-5.6-sol", total=100, cached=20),
    _record("alpha", "Alpha", "subagent", "gpt-5.6-terra", total=40),
    _record("alpha", "Alpha", "subagent", "gpt-5.6-luna", total=10),
    _record("beta", "Beta", "root", "gpt-5.6-sol", total=30),
]

breakdown = build_report_breakdown(records)

assert [project.row.key for project in breakdown.projects] == ["alpha", "beta"]
alpha = breakdown.projects[0]
assert alpha.row.usage.total_tokens == 150
assert [(role.role, role.total.usage.total_tokens) for role in alpha.roles] == [
    ("root", 100),
    ("subagent", 50),
]
assert [bucket.label for bucket in breakdown.visual_models] == [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
]
```

Add assertions that summing role/model rows reproduces each project's `TokenUsage`, `CostBreakdown`, `CreditBreakdown`, unpriced fields, and record count. Use `pytest.approx(abs=1e-9)` for floating point cost/credit fields and exact equality for integer fields.

- [ ] **Step 2: Write failing top-seven-plus-Other tests**

Create nine exact models with descending totals, plus a tie between the seventh and eighth models. Assert ordering uses model id for the tie, only seven exact visual buckets remain, and the rest are in `Other`:

```python
assert [bucket.label for bucket in breakdown.visual_models[:-1]] == expected_top_seven
assert breakdown.visual_models[-1].key == OTHER_MODEL_KEY
assert breakdown.visual_models[-1].label == "Other"
assert breakdown.visual_models[-1].exact_models == tuple(sorted(expected_other_models))
assert breakdown.visual_model_rows[-1].usage.total_tokens == sum(other_totals)
assert [row.label for row in breakdown.model_rows] == expected_all_exact_models
```

Repeat the same input in reverse order and assert the visual model definitions are identical. Add cases for fewer than seven models, an unknown model id, root-only projects, subagent-only projects, and an empty record list.

- [ ] **Step 3: Run aggregation tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_report_breakdown.py
```

Expected: collection fails because `report_breakdown.py` and its public dataclasses do not exist.

- [ ] **Step 4: Add composable record summaries**

In `aggregation.py`, add:

```python
def summarize_record(record: UsageRecord) -> UsageSummary:
    return UsageSummary(
        usage=record.usage,
        cost=_record_cost(record),
        credits=_record_credits(record),
        record_count=1,
    )
```

Add the immutable combining operation:

```python
def add(self, other: "UsageSummary") -> "UsageSummary":
    return UsageSummary(
        usage=self.usage.add(other.usage),
        cost=self.cost.add(other.cost),
        credits=self.credits.add(other.credits),
        record_count=self.record_count + other.record_count,
    )
```

Use `summarize_record(record)` inside `aggregate_records()` and `summarize_records()` so pricing logic has one implementation.

- [ ] **Step 5: Define the immutable cube contract**

Create these public dataclasses in `report_breakdown.py`:

```python
@dataclass(frozen=True, slots=True)
class VisualModelBucket:
    key: str
    label: str
    exact_models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleModelBreakdown:
    role: UsageRole
    total: UsageSummary
    model_rows: tuple[AggregateRow, ...]


@dataclass(frozen=True, slots=True)
class ProjectRoleModelBreakdown:
    row: AggregateRow
    roles: tuple[RoleModelBreakdown, ...]


@dataclass(frozen=True, slots=True)
class ReportBreakdown:
    visual_models: tuple[VisualModelBucket, ...]
    projects: tuple[ProjectRoleModelBreakdown, ...]
    model_rows: tuple[AggregateRow, ...]
    visual_model_rows: tuple[AggregateRow, ...]

    @property
    def project_rows(self) -> tuple[AggregateRow, ...]:
        return tuple(project.row for project in self.projects)
```

Use `ROOT_USAGE_ROLE` then `SUBAGENT_USAGE_ROLE` as the fixed role order.

- [ ] **Step 6: Build the cube in one record pass**

Implement `build_report_breakdown()` with one loop that accumulates four maps:

```python
project_role_model: dict[str, dict[UsageRole, dict[str, UsageSummary]]] = {}
project_totals: dict[str, UsageSummary] = {}
project_labels: dict[str, str] = {}
model_totals: dict[str, UsageSummary] = {}

for record in records:
    record_summary = summarize_record(record)
    project_labels[record.project_key] = record.project_label
    project_totals[record.project_key] = _add(
        project_totals.get(record.project_key), record_summary
    )
    model_totals[record.model] = _add(model_totals.get(record.model), record_summary)
    role_models = project_role_model.setdefault(record.project_key, {}).setdefault(
        record.usage_role, {}
    )
    role_models[record.model] = _add(role_models.get(record.model), record_summary)
```

`_add(None, value)` returns `value`; otherwise it calls `UsageSummary.add`. Select visual models from `model_totals` using `(-total_tokens, model_id)`. Build `Other` only when exact models remain outside the configured limit. Freeze every role's exact-model summaries into the ordered visual buckets by adding the summaries of `bucket.exact_models`; omit zero-token rows.

Create `AggregateRow` values through one helper:

```python
def _row(key: str, label: str, summary: UsageSummary) -> AggregateRow:
    return AggregateRow(
        key=key,
        label=label,
        usage=summary.usage,
        cost=summary.cost,
        credits=summary.credits,
        record_count=summary.record_count,
    )
```

Sort projects by `(-total_tokens, project_key)` and exact model rows by `(-total_tokens, model_id)`.

- [ ] **Step 7: Enforce conservation before returning**

Add `_validate_breakdown(report: ReportBreakdown) -> None`. For each project, sum role totals and compare against `project.row`; for each role, sum model rows and compare against `role.total`; compare exact global model rows against visual model rows. Compare all six `TokenUsage` stored fields, all `CostBreakdown` stored fields, all `CreditBreakdown` stored fields, and `record_count`.

Use exact integer comparison and:

```python
math.isclose(actual_float, expected_float, rel_tol=0.0, abs_tol=1e-9)
```

for cost/credit floats. Raise `ValueError` naming the failed scope and field. Call this validator once before returning from `build_report_breakdown()`.

- [ ] **Step 8: Run focused and pricing regression tests**

Run:

```bash
uv run pytest -q tests/test_report_breakdown.py tests/test_parser_aggregation.py tests/test_pricing.py tests/test_pricing_gpt_5_6_reduction.py
```

Expected: all tests pass; top-seven selection is deterministic and effective-dated costs/credits conserve through `Other`.

- [ ] **Step 9: Commit the one-pass aggregation layer**

```bash
git add src/codex_usage/aggregation.py src/codex_usage/report_breakdown.py tests/test_report_breakdown.py
git commit -m "feat: aggregate project usage by role and model"
```

---
### Task 3: Presentation View Model And Report Command Wiring

**Files:**
- Create: `src/codex_usage/report_breakdown_view.py`
- Create: `tests/test_report_command_breakdown.py`
- Modify: `src/codex_usage/report_view.py:1-121,172-182`
- Modify: `src/codex_usage/cli.py:215-238`
- Modify: `src/codex_usage/reporting.py:11-202`
- Modify: `tests/test_report_view.py`
- Modify: `tests/test_reporting_html.py`

**Interfaces:**
- Consumes: `ReportBreakdown` from Task 2.
- Produces: `ModelLegendItem`, `ModelSegmentPoint`, `RoleGroupPoint`, `ProjectBreakdownPoint`, `ModelMixPoint`, and `BreakdownView` in `report_breakdown_view.py`.
- Produces: `build_breakdown_view(breakdown: ReportBreakdown) -> BreakdownView`.
- Changes: `build_report_view_model()` to the exact keyword-only signature in Step 5; remove the `project_rows` and `model_rows` parameters.
- Changes: `render_html_report()` to the exact keyword-only signature in Step 6; remove the `project_rows` and `model_rows` parameters.
- Preserves: `ReportViewModel.project_rows` and `model_rows` as exact `AggregateRow` lists for pricing notices and exact tables.

- [ ] **Step 1: Write failing presentation mapping tests**

Rewrite `tests/test_report_view.py` to build records, call `build_report_breakdown()`, and pass the result to `build_report_view_model()`. Assert:

```python
assert [item.label for item in view_model.model_legend] == [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
]
assert [item.color_slot for item in view_model.model_legend] == [0, 1, 2]

project = view_model.project_points[0]
assert project.label == "demo"
assert project.root_tokens == 1_000
assert project.subagent_tokens == 100
assert [(group.role, group.label) for group in project.roles] == [
    ("root", "Root tasks"),
    ("subagent", "Subagents"),
]
assert project.roles[0].project_share == pytest.approx(1_000 / 1_100)
assert project.roles[1].segments[0].project_share == pytest.approx(100 / 1_100)
assert view_model.project_detail_points == view_model.breakdown_view.project_points
```

Add more than twelve projects and assert `project_points` contains twelve while `project_detail_points` retains all projects. Add eight visual buckets and assert the last legend/model point uses color slot `7` for `Other`; exact top-seven buckets use slots `0` through `6`.

- [ ] **Step 2: Write a failing command-level no-duplicate-aggregation test**

Create `tests/test_report_command_breakdown.py`. Patch `cli.load_usage_context` with a one-record `UsageContext`, wrap `cli.aggregate_records`, and replace `cli.render_html_report` with a capture function. Invoke `handle_report()` with `theme="night"`.

```python
aggregate_groups: list[str] = []

def track_aggregate(records, group_by, timezone):
    aggregate_groups.append(group_by)
    return aggregate_records(records, group_by, timezone)

monkeypatch.setattr(cli, "aggregate_records", track_aggregate)

assert cli.handle_report(args) == 0
assert aggregate_groups == ["day", "hour"]
assert captured["breakdown"].project_rows[0].key == "repo"
```

The capture function must accept the final `render_html_report` keyword contract and return `args.output`.

- [ ] **Step 3: Run view/command tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_report_view.py tests/test_report_command_breakdown.py
```

Expected: tests fail because the presentation dataclasses and `breakdown` report argument do not exist.

- [ ] **Step 4: Define presentation-only breakdown points**

Create `report_breakdown_view.py` with these frozen contracts:

```python
@dataclass(frozen=True, slots=True)
class ModelLegendItem:
    key: str
    label: str
    color_slot: int


@dataclass(frozen=True, slots=True)
class ModelSegmentPoint:
    key: str
    label: str
    color_slot: int
    total_tokens: int
    cost_usd: float
    total_credits: float
    unpriced_tokens: int
    credit_unpriced_tokens: int
    record_count: int
    project_share: float


@dataclass(frozen=True, slots=True)
class RoleGroupPoint:
    role: UsageRole
    label: str
    total_tokens: int
    project_share: float
    segments: tuple[ModelSegmentPoint, ...]


@dataclass(frozen=True, slots=True)
class ProjectBreakdownPoint:
    key: str
    label: str
    usage: TokenUsage
    cost: CostBreakdown
    credits: CreditBreakdown
    record_count: int
    root_tokens: int
    subagent_tokens: int
    roles: tuple[RoleGroupPoint, ...]

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    @property
    def cost_usd(self) -> float:
        return self.cost.total_usd

    @property
    def total_credits(self) -> float:
        return self.credits.total_credits

    @property
    def unpriced_tokens(self) -> int:
        return self.cost.unpriced_tokens

    @property
    def credit_unpriced_tokens(self) -> int:
        return self.credits.unpriced_tokens


@dataclass(frozen=True, slots=True)
class ModelMixPoint:
    key: str
    label: str
    color_slot: int
    total_tokens: int
    cost_usd: float
    total_credits: float
    unpriced_tokens: int
    credit_unpriced_tokens: int
    record_count: int


@dataclass(frozen=True, slots=True)
class BreakdownView:
    model_legend: tuple[ModelLegendItem, ...]
    project_points: tuple[ProjectBreakdownPoint, ...]
    model_points: tuple[ModelMixPoint, ...]
```

Assign exact buckets their ordered slots `0..6`; assign `OTHER_MODEL_KEY` slot `7` regardless of whether fewer colors precede it. Map role labels with a closed dictionary for `root` and `subagent`. Compute every role and segment `project_share` against the complete project total, using zero only when the project total is zero.

- [ ] **Step 5: Integrate the breakdown view into `ReportViewModel`**

Change the relevant fields to:

```python
breakdown_view: BreakdownView
model_legend: list[ModelLegendItem]
project_points: list[ProjectBreakdownPoint]
project_detail_points: list[ProjectBreakdownPoint]
model_points: list[ModelMixPoint]
project_rows: list[AggregateRow]
model_rows: list[AggregateRow]
```

Replace `build_report_view_model()` with this exact keyword-only signature:

```python
def build_report_view_model(
    *,
    generated_at: datetime,
    range_name: str,
    total: UsageSummary,
    daily_rows: list[AggregateRow],
    hourly_rows: list[AggregateRow],
    breakdown: ReportBreakdown,
    sessions_dirs: list[Path],
    files_scanned: int,
    files_archived: int = 0,
    files_retained_missing: int = 0,
    storage_roots: list[str] | tuple[str, ...] | None = None,
) -> ReportViewModel:
```

Inside `build_report_view_model()`:

```python
breakdown_view = build_breakdown_view(breakdown)
return ReportViewModel(
    generated_at=generated_at,
    range_name=range_name,
    sessions_dirs=sessions_dirs,
    files_scanned=files_scanned,
    files_archived=files_archived,
    files_retained_missing=files_retained_missing,
    storage_roots=tuple(storage_roots or [str(path) for path in sessions_dirs]),
    total=total,
    kpis=_build_kpis(total),
    daily_points=[_daily_point(row) for row in daily_rows],
    hourly_cells=[
        cell for row in hourly_rows if (cell := _hourly_cell(row)) is not None
    ],
    breakdown_view=breakdown_view,
    model_legend=list(breakdown_view.model_legend),
    project_points=list(breakdown_view.project_points[:12]),
    project_detail_points=list(breakdown_view.project_points),
    model_points=list(breakdown_view.model_points),
    daily_rows=daily_rows,
    hourly_rows=hourly_rows,
    project_rows=list(breakdown.project_rows),
    model_rows=list(breakdown.model_rows),
)
```

Remove `_breakdown_point()` from `report_view.py`; daily/hourly points and KPI behavior remain unchanged.

- [ ] **Step 6: Replace duplicate project/model report aggregation**

Change `render_html_report()` to this exact keyword-only signature:

```python
def render_html_report(
    *,
    output_path: Path,
    generated_at: datetime,
    range_name: str,
    total: UsageSummary,
    daily_rows: list[AggregateRow],
    hourly_rows: list[AggregateRow],
    breakdown: ReportBreakdown,
    sessions_dirs: list[Path],
    files_scanned: int,
    storage_roots: list[str] | None = None,
    files_archived: int = 0,
    files_retained_missing: int = 0,
    project_keys: list[str] | None = None,
    project_transitions: list[dict[str, object]] | None = None,
    theme: str = "auto",
) -> Path:
```

Pass `breakdown=breakdown` from `render_html_report()` to `build_report_view_model()`. In `handle_report()`, build the cube once and use the complete call below, retaining the existing local variable names for report metadata:

```python
breakdown = build_report_breakdown(context.records)
output_path = render_html_report(
    output_path=args.output,
    generated_at=datetime.now(context.timezone),
    range_name=args.range_name,
    total=total,
    daily_rows=aggregate_records(context.records, "day", context.timezone),
    hourly_rows=aggregate_records(context.records, "hour", context.timezone),
    breakdown=breakdown,
    sessions_dirs=context.session_dirs,
    files_scanned=len(context.files),
    storage_roots=[str(path) for path in context.session_dirs],
    files_archived=context.storage_stats.files_archived,
    files_retained_missing=context.storage_stats.files_missing_retained,
    project_keys=context.project_keys,
    project_transitions=_transition_dicts(context.project_transitions),
    theme=normalize_report_theme(args.theme or get_settings().theme),
)
```

Delete the report command's `aggregate_records(context.records, "project", context.timezone)` and `aggregate_records(context.records, "model", context.timezone)` calls. Do not change `handle_summary()`, whose requested `--by` behavior still uses `aggregate_records()`.

Change `render_html_report()` and `build_report_view_model()` to require `breakdown`. Continue passing exact `breakdown.project_rows` and `breakdown.model_rows` to existing tables until Task 4 replaces the project table renderer.

- [ ] **Step 7: Update existing HTML test fixtures to the new required argument**

In `tests/test_reporting_html.py`, add a `_breakdown(project_rows, model_rows)` helper that constructs `VisualModelBucket`, `RoleModelBreakdown`, `ProjectRoleModelBreakdown`, and `ReportBreakdown` directly from the existing synthetic rows. Use a single root role for the old rendering tests, and pass `breakdown=_breakdown(project_rows, model_rows)` instead of separate `project_rows=` and `model_rows=` arguments.

The helper converts an `AggregateRow` to `UsageSummary` with:

```python
def _summary(row: AggregateRow) -> UsageSummary:
    return UsageSummary(
        usage=row.usage,
        cost=row.cost,
        credits=row.credits,
        record_count=row.record_count,
    )
```

This test-only constructor does not call the production validator; production reports always receive `build_report_breakdown()` output.

- [ ] **Step 8: Run report-view, command, HTML, and CLI tests**

Run:

```bash
uv run pytest -q tests/test_report_view.py tests/test_report_command_breakdown.py tests/test_reporting_html.py tests/test_cli.py tests/test_token_usage.py
```

Expected: all tests pass, HTML still renders, and report command aggregation calls are exactly `day` and `hour` plus one cube build.

- [ ] **Step 9: Commit presentation wiring**

```bash
git add src/codex_usage/report_breakdown_view.py src/codex_usage/report_view.py src/codex_usage/cli.py src/codex_usage/reporting.py tests/test_report_view.py tests/test_report_command_breakdown.py tests/test_reporting_html.py
git commit -m "feat: prepare role and model report views"
```

---

### Task 4: Accessible Nested Role/Model Charts And Project Details

**Files:**
- Create: `src/codex_usage/report_breakdown_theme.py`
- Create: `src/codex_usage/report_tables.py`
- Create: `tests/test_project_breakdown_html.py`
- Modify: `src/codex_usage/charts.py:1-192`
- Modify: `src/codex_usage/report_theme.py:14-471`
- Modify: `src/codex_usage/reporting.py:11-409`
- Modify: `tests/test_reporting_html.py`
- Modify: `tests/test_python_source_size.py` only if a newly split module needs explicit coverage clarification; do not add a new oversized-file exception.

**Interfaces:**
- Consumes: `ProjectBreakdownPoint`, `ModelMixPoint`, and `ModelLegendItem` from Task 3.
- Produces: `render_project_breakdown_chart(points, legend) -> str` and `render_model_mix_chart(points) -> str` in `charts.py`.
- Produces: `render_aggregate_table(title, rows, *, section_id) -> str` and `render_project_details_table(title, points, *, section_id) -> str` in `report_tables.py`.
- Produces: `report_breakdown_css() -> str`, concatenated by `report_theme.report_css()`.
- Produces: stable section attributes `data-report-section="daily-cost"`, `"hourly-heatmap"`, `"project-breakdown"`, `"project-details"`, `"model-mix"`, and `"model-details"` for screenshot automation.

- [ ] **Step 1: Write failing mixed-role HTML and accessibility tests**

Create `tests/test_project_breakdown_html.py` with a mixed project containing root Sol/Terra segments and subagent Terra/Luna segments. Render the report and assert:

```python
assert 'data-report-section="project-breakdown"' in report_html
assert 'class="project-role-groups has-role-gap"' in report_html
assert '>Root tasks<' in report_html
assert '>Subagents<' in report_html
assert 'role="group" aria-label="demo Root tasks' in report_html
assert 'tabindex="0"' in report_html
assert "demo, Root tasks, gpt-5.6-sol" in report_html
assert "tokens, 54.5% of project" in report_html
assert 'class="model-color-slot-0"' in report_html
assert 'class="model-color-slot-1"' in report_html
```

Assert the visible legend contains every visual model exactly once and that the Model Mix row for each model uses the same `model-color-slot-N` class as its project segments. Assert `Other` uses slot 7.

- [ ] **Step 2: Write failing layout and edge-case tests**

Add separate tests for:

- root-only project: one role group and no `has-role-gap` class;
- subagent-only project: one role group labeled `Subagents`;
- tiny positive subagent/model shares: nonzero proportional `fr`/percentage styles, focusable segment, complete aria text, and no forced 1% minimum;
- unknown model: retained unpriced disclosures in tooltip and table;
- empty report: existing chart empty state;
- project table: `Root Tokens` and `Subagent Tokens` columns with complete project totals;
- model table: all exact models remain present even when the visual chart has `Other`;
- stable `project-details` and `model-details` section identifiers;
- day, night, and VS Code high-contrast variables;
- no `<script`, remote `src=`, or remote `href=` attributes.

- [ ] **Step 3: Run rendering tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_project_breakdown_html.py tests/test_reporting_html.py
```

Expected: tests fail because Project Breakdown still renders one solid bar and Project Details has no role columns.

- [ ] **Step 4: Render nested project role/model groups**

Replace `render_project_breakdown_svg()` with the accurately named `render_project_breakdown_chart()`. Preserve absolute project scaling:

```python
max_tokens = max(point.total_tokens for point in points) or 1
outer_width = point.total_tokens / max_tokens * 100
```

For each project, compute and render the outer row with these exact values:

```python
outer_width = point.total_tokens / max_tokens * 100
role_gap_class = " has-role-gap" if len(point.roles) == 2 else ""
role_columns = " ".join(f"{role.total_tokens}fr" for role in point.roles)
role_headings = "".join(_render_role_heading(role) for role in point.roles)
role_groups = "".join(_render_role_group(point, role) for role in point.roles)
row_html = (
    '<div class="project-breakdown-row">'
    f'<span class="breakdown-bar-label">{html.escape(point.label)}</span>'
    '<div class="project-track">'
    f'<div class="project-role-stack" style="width:{outer_width:.4f}%">'
    f'<div class="project-role-labels{role_gap_class}" '
    f'style="grid-template-columns:{role_columns}">{role_headings}</div>'
    f'<div class="project-role-groups{role_gap_class}" '
    f'style="grid-template-columns:{role_columns}">{role_groups}</div>'
    '</div></div>'
    f'<span class="breakdown-bar-value">{_breakdown_value(point)}</span>'
    '</div>'
)
```

Within `_render_role_group()`, use the complete role-local percentage and preescaped tooltip/aria strings:

```python
segment_width = (
    segment.total_tokens / role.total_tokens * 100 if role.total_tokens else 0
)
segment_html = (
    f'<span class="model-segment model-color-slot-{segment.color_slot}" '
    f'style="width:{segment_width:.4f}%" tabindex="0" '
    f'aria-label="{html.escape(segment_aria, quote=True)}">'
    f'<span class="chart-tooltip"><strong>{tooltip_title}</strong>'
    f'<span>{tooltip_detail}</span></span></span>'
)
```

Use `gap: 8px` only when two role groups exist. Use each role's token total as its grid fraction; use each segment's role-local token share as its width. Do not clamp positive values to a percentage minimum. Render visible role headings as `Root tasks` or `Subagents` plus compact tokens/project share; allow CSS to hide the heading text in narrow role containers while keeping segment aria labels and tooltips complete.

Use tooltip main text `"{project} · {role label} · {model label}"` and detail text:

```text
{tokens} tokens | {share:.1%} of project | ${cost:.4f} | {credits} credits
```

Append API-excluded and no-credit-rate text when nonzero. Segment aria text uses commas instead of visual separators.

Render one legend after project rows:

```html
<div class="model-legend" aria-label="Model colors">
  <span class="model-legend-item"><span class="model-swatch model-color-slot-0"></span>gpt-5.6-sol</span>
</div>
```

- [ ] **Step 5: Apply shared model colors to Model Mix**

Replace `render_model_mix_svg()` with `render_model_mix_chart()`. Keep one horizontal row per visual model, but add its `model-color-slot-N` class to the fill. Model Mix receives the visual rows from Task 3, so it includes at most seven exact models plus `Other`. Keep its complete tooltip and right-side token/cost/credit total.

Use these shared CSS variables:

```css
--model-0: #8fb1f5;
--model-1: #3978e6;
--model-2: #315a9f;
--model-3: #b59af1;
--model-4: #7d4dde;
--model-5: #dd6a9e;
--model-6: #d9aa2b;
--model-7: #8b949f;
```

Night mode may use slightly brighter equivalents, but slot identity must not change. High-contrast mode keeps segment borders and focus outlines visible even when colors converge.

- [ ] **Step 6: Split chart CSS before extending it**

Create `report_breakdown_theme.py` and move the existing `.breakdown-bar-*` rules out of `report_theme.py`. Add all new project-role, segment, legend, shared model color, container-query, hover/focus, and narrow-view rules there. Export:

```python
def report_breakdown_css() -> str:
    return "\n".join((_MODEL_COLOR_CSS, _PROJECT_BREAKDOWN_CSS, _MODEL_MIX_CSS))
```

Define all three constants as complete module-level CSS strings; do not leave chart rules duplicated in `report_theme.py`.

Make `report_css()` concatenate its existing base CSS and `report_breakdown_css()`. Keep both files below 500 lines. Use a focus ring and brightness/filter adjustment instead of replacing the model color with `--accent-strong`.

Required layout rules include:

```css
.project-role-groups { display: grid; height: 34px; }
.project-role-groups.has-role-gap,
.project-role-labels.has-role-gap { gap: 8px; }
.project-role-group { display: flex; overflow: hidden; border: 1px solid var(--border); border-radius: 4px; }
.model-segment { position: relative; display: block; height: 100%; outline: none; }
.model-segment:focus-visible { box-shadow: inset 0 0 0 2px var(--text); z-index: 3; }
.project-role-heading { container-type: inline-size; overflow: hidden; }
@container (max-width: 120px) { .project-role-heading-detail { display: none; } }
```

Keep the existing 80 px tooltip reserve so focused tooltips remain inside the scroll container's vertical bounds.

- [ ] **Step 7: Split table rendering and add role columns**

Create `report_tables.py`, move the generic `_table_section()` implementation into `render_aggregate_table()`, and add `render_project_details_table()` using `ProjectBreakdownPoint` values. Require an explicit keyword-only `section_id` in both functions and emit it as an escaped `data-report-section` value on the surrounding `<section>`. The project header order is:

```text
Label | Total | Root Tokens | Subagent Tokens | Input | Cache Read | Cache Write | Output | API Cost | Codex Credits | API Excl. | No Credit Rate | Share
```

`ProjectBreakdownPoint` already retains `usage: TokenUsage`, `cost: CostBreakdown`, and `credits: CreditBreakdown` from Task 3. Read the complete categories from those objects and the scalar convenience properties; never reconstruct categories from totals.

Import both table renderers into `reporting.py`, remove its private table renderer/formatters, and use:

```python
render_project_details_table(
    "Project Details",
    view_model.project_detail_points,
    section_id="project-details",
)
render_aggregate_table(
    "Model Details",
    view_model.model_rows,
    section_id="model-details",
)
```

- [ ] **Step 8: Add stable section identifiers and wire the new renderers**

Change `_chart_section()` to require `section_id: str` and emit:

```html
<section class="section" data-report-section="project-breakdown">
```

Pass the four chart identifiers listed in this task's interface and the two table identifiers from Step 7. Wire `render_project_breakdown_chart(view_model.project_points, view_model.model_legend)` and `render_model_mix_chart(view_model.model_points)`.

- [ ] **Step 9: Run rendering, accessibility, size, and report regression tests**

Run:

```bash
uv run pytest -q tests/test_project_breakdown_html.py tests/test_reporting_html.py tests/test_report_view.py tests/test_python_source_size.py
```

Expected: all tests pass; both role groups and the shared model palette render without scripts or remote assets, and every changed Python file remains below 500 lines.

- [ ] **Step 10: Commit the accessible dashboard rendering**

```bash
git add src/codex_usage/charts.py src/codex_usage/report_breakdown_theme.py src/codex_usage/report_tables.py src/codex_usage/report_theme.py src/codex_usage/reporting.py src/codex_usage/report_breakdown_view.py tests/test_project_breakdown_html.py tests/test_reporting_html.py tests/test_report_view.py tests/test_python_source_size.py
git commit -m "feat: render project role and model stacks"
```

---

### Task 5: Reproducible Playwright Marketplace Screenshot

**Files:**
- Create: `scripts/generate_marketplace_screenshot.py`
- Create: `tests/test_marketplace_screenshot.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.github/workflows/package-vsix.yml`
- Modify: `tests/test_github_actions_workflow.py`
- Regenerate: `docs/marketplace/dashboard-synthetic.png`

**Interfaces:**
- Produces: `build_synthetic_records() -> list[UsageRecord]` with fixed dates, projects, roles, and models.
- Produces: `render_synthetic_report(destination: Path) -> Path` using production aggregation and report rendering.
- Produces: `capture_marketplace_screenshot(report_path: Path, output_path: Path) -> None` using Python Playwright Chromium.
- Produces: `validate_screenshot(path: Path) -> None` using Pillow.
- Produces CLI: `uv run python scripts/generate_marketplace_screenshot.py [--check]`.
- `--check` renders and validates a temporary screenshot without replacing the tracked PNG; the default command writes the tracked PNG and validates it.

- [ ] **Step 1: Write failing synthetic-data and generator tests**

Create `tests/test_marketplace_screenshot.py`. Import the script through `importlib.util.spec_from_file_location` as existing script tests do. Assert the fixed corpus contains no personal paths, both roles, at least two projects, and more than seven exact models so `Other` appears:

```python
records = screenshot_module.build_synthetic_records()

assert {record.usage_role for record in records} == {"root", "subagent"}
assert len({record.project_key for record in records}) >= 2
assert len({record.model for record in records}) >= 8
assert all("/Users/" not in str(record.file_path) for record in records)
assert all("C:\\Users\\" not in str(record.file_path) for record in records)

breakdown = build_report_breakdown(records)
assert breakdown.visual_models[-1].label == "Other"
```

Render only the HTML in a temporary directory and assert it contains `data-report-section="project-breakdown"`, both role labels, `model-color-slot-7`, and no script/remote asset tags. Test argument parsing by monkeypatching capture/validation functions and asserting `--check` does not write `docs/marketplace/dashboard-synthetic.png`.

- [ ] **Step 2: Add failing workflow coverage**

Extend `tests/test_github_actions_workflow.py` to require one macOS-only screenshot gate after Python tests:

```python
assert "uv run playwright install chromium" in workflow_text
assert "uv run python scripts/generate_marketplace_screenshot.py --check" in workflow_text
```

Also assert neither command is duplicated in the Windows job. Parse the YAML text by job boundaries using the existing workflow-test helpers rather than relying on a repository-wide count.

- [ ] **Step 3: Run generator/workflow tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_marketplace_screenshot.py tests/test_github_actions_workflow.py
```

Expected: tests fail because the generator, dependencies, and workflow steps do not exist.

- [ ] **Step 4: Add development-only browser/image dependencies**

Run:

```bash
uv add --dev playwright pillow
```

Expected: `pyproject.toml` gains Playwright and Pillow only under the `dev` dependency group, and `uv.lock` updates. Do not add either package to runtime dependencies or bundled VSIX requirements.

- [ ] **Step 5: Implement the fixed synthetic production report**

In `scripts/generate_marketplace_screenshot.py`, resolve `REPOSITORY_ROOT` from `__file__` and define:

```python
SCREENSHOT_PATH = REPOSITORY_ROOT / "docs" / "marketplace" / "dashboard-synthetic.png"
VIEWPORT = {"width": 1440, "height": 900}
```

Build deterministic records at fixed UTC timestamps after 2026-07-31. Use synthetic project keys such as `https://github.com/example/codex-usage` and `https://github.com/example/translation-tools`, fixed file paths beneath `/synthetic/codex/sessions`, both roles in every displayed project, and these exact models:

```text
gpt-5.6-sol
gpt-5.6-terra
gpt-5.6-luna
gpt-5.5
gpt-5.4-mini
gpt-5.4
gpt-5.3-codex
synthetic-unpriced-model
```

Give Sol, Terra, and Luna enough usage to remain the first three visual models. Give the last model the smallest total so it enters `Other` and exercises unpriced disclosures.

`render_synthetic_report()` must call the same production functions as the CLI:

```python
records = build_synthetic_records()
breakdown = build_report_breakdown(records)
return render_html_report(
    output_path=destination,
    generated_at=FIXED_GENERATED_AT,
    range_name="30d",
    total=summarize_records(records),
    daily_rows=aggregate_records(records, "day", UTC),
    hourly_rows=aggregate_records(records, "hour", UTC),
    breakdown=breakdown,
    sessions_dirs=[Path("/synthetic/codex/sessions")],
    files_scanned=len({record.file_path for record in records}),
    theme="night",
)
```

- [ ] **Step 6: Implement Playwright capture and DOM clipping checks**

Launch Chromium with `sync_playwright()`, open the temporary report through `Path.as_uri()`, and inject screenshot-only CSS that:

- hides the daily and hourly sections by `data-report-section`;
- hides `project-details` and `model-details` by `data-report-section`;
- keeps the report title, KPI row, Project Breakdown, and Model Mix;
- expands `main` to the 1440 px viewport without changing chart markup.

Before capture, require these landmarks with Playwright locators:

```python
page.get_by_role("heading", name="Project Breakdown", exact=True).wait_for()
page.get_by_text("Root tasks", exact=True).first.wait_for()
page.get_by_text("Subagents", exact=True).first.wait_for()
page.get_by_role("heading", name="Model Mix", exact=True).wait_for()
page.get_by_text("Other", exact=True).last.wait_for()
```

Focus the first and last `.model-segment`, then compare the visible `.chart-tooltip` bounding box with the corresponding `.tooltip-chart-scroll` and viewport. Require non-null boxes, `tooltip.y >= scroll.y`, `tooltip.x >= 0`, and `tooltip.x + tooltip.width <= 1440`. Require every `.project-role-group` box to have positive width/height and stay inside its `.project-role-stack` box. Repeat the overlap/scrollability assertions at a 720 x 900 viewport without creating the tracked image.

Capture exactly 1440 x 900 with:

```python
page.set_viewport_size(VIEWPORT)
page.screenshot(path=str(output_path), full_page=False)
```

Close the browser in a `finally` block.

- [ ] **Step 7: Validate dimensions and meaningful pixels**

Use Pillow:

```python
with Image.open(path) as image:
    if image.size != (1440, 900):
        raise RuntimeError(f"unexpected screenshot dimensions for {path}: {image.size}")
    rgb = image.convert("RGB")
    extrema = rgb.getextrema()
    if not all(high > low for low, high in extrema):
        raise RuntimeError(f"screenshot has a flat color channel: {path}")
    colors = rgb.resize((180, 112)).getcolors(maxcolors=180 * 112)
    if colors is None or len(colors) < 32:
        raise RuntimeError(f"screenshot lacks meaningful visual variation: {path}")
```

Keep pytest assertions in the test module.

- [ ] **Step 8: Implement `--check` and regenerate the tracked screenshot**

Use `argparse` with one boolean `--check`. In check mode, create a `TemporaryDirectory`, render HTML and PNG there, validate, and leave the tracked PNG untouched. In default mode, render through a temporary HTML file, write `SCREENSHOT_PATH`, and validate it.

Install Chromium once and run both paths:

```bash
uv run playwright install chromium
uv run python scripts/generate_marketplace_screenshot.py
uv run python scripts/generate_marketplace_screenshot.py --check
```

Expected: both commands succeed; the tracked PNG is 1440 x 900 and visibly features Project Breakdown followed by Model Mix with complete tooltips and role headings.

- [ ] **Step 9: Add the macOS CI screenshot gate**

In the macOS job after `Run Python tests`, add:

```yaml
      - name: Install screenshot browser
        run: uv run playwright install chromium

      - name: Verify Marketplace screenshot renderer
        run: uv run python scripts/generate_marketplace_screenshot.py --check
```

Do not add browser installation to Windows or the publish-only Ubuntu job.

- [ ] **Step 10: Run screenshot, workflow, and full rendering tests**

Run:

```bash
uv run pytest -q tests/test_marketplace_screenshot.py tests/test_github_actions_workflow.py tests/test_project_breakdown_html.py tests/test_reporting_html.py
uv run python scripts/generate_marketplace_screenshot.py --check
git diff --check
```

Expected: all tests pass, the browser check passes at desktop and narrow widths, and whitespace validation prints nothing.

- [ ] **Step 11: Commit screenshot automation and the regenerated image**

```bash
git add pyproject.toml uv.lock scripts/generate_marketplace_screenshot.py tests/test_marketplace_screenshot.py .github/workflows/package-vsix.yml tests/test_github_actions_workflow.py docs/marketplace/dashboard-synthetic.png
git commit -m "test: automate marketplace dashboard screenshot"
```

---

### Task 6: Feature-First README, Marketplace, Release, And Changelog Copy

**Files:**
- Create: `tests/test_project_role_model_docs.py`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `docs/release.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`

**Interfaces:**
- Consumes: the stable screenshot command and tracked image from Task 5.
- Produces: feature-first repository and Marketplace copy using `root tasks`, `subagents`, `model mix`, and `Task Transfer` consistently.
- Produces: release-checklist commands for browser setup, screenshot regeneration, automated checking, and human visual review.
- Preserves: historical changelog entries, including the dated schema-4 release record.

- [ ] **Step 1: Write failing documentation-contract tests**

Create `tests/test_project_role_model_docs.py` and load both READMEs, both changelogs, and `docs/release.md`. Require the opening reporting sections to include these phrases case-insensitively:

```text
root tasks
subagents
model
project
Codex credits
API-equivalent
Task Transfer
```

Assert the Task Transfer heading appears after the reporting feature copy. Require the release checklist to include:

```text
uv run playwright install chromium
uv run python scripts/generate_marketplace_screenshot.py
uv run python scripts/generate_marketplace_screenshot.py --check
1440 x 900
visually review
```

Require both Unreleased changelog sections to mention explicit root/subagent usage, shared model colors, visual-only `Other`, and the one-time schema 5 rebuild. Assert the historical `1.1.0` sections still mention schema 4.

- [ ] **Step 2: Run documentation tests and verify failure**

Run:

```bash
uv run pytest -q tests/test_project_role_model_docs.py tests/test_release_history.py
```

Expected: the new contract test fails because the READMEs and Unreleased sections do not describe the feature.

- [ ] **Step 3: Lead both READMEs with the reporting capability**

Use this information hierarchy before package installation details:

1. Local-first Codex usage reporting.
2. Per-project root-task versus subagent split.
3. Model composition inside each role plus shared Model Mix colors.
4. Effective-dated API-equivalent USD and Codex credit estimates.
5. Optional Task Transfer as the second major capability.

Update `What The Dashboard Shows` and extension `Features` bullets to say that Project Breakdown separates user-visible root tasks from structured subagents and then stacks each role by model. Explain that Model Details remains exact while crowded charts group models after the largest seven into `Other`.

Keep the screenshot directly below the opening feature copy in both READMEs. Do not describe automatic reviews or guardians as user-visible tasks.

- [ ] **Step 4: Update the performance-cache explanation for schema 5**

Replace present-tense schema-4 upgrade wording with:

```text
The first report after the project role/model update builds the disposable schema 5 cache once so every usage row carries an explicit root/subagent role. Later reports continue to inspect only changed files and query the selected time range from local SQLite. The role/model breakdown is aggregated from those already range-filtered records and does not rescan source JSONL files.
```

Retain the existing `Loaded in X.X seconds`, parent-owned SQLite, range-aware query, and no-live-pricing explanations. Historical changelog entries continue to describe schema 4 as the 1.1.0 state.

- [ ] **Step 5: Add the screenshot release gate**

Add a `Marketplace Screenshot` section to `docs/release.md`:

```bash
uv sync
uv run playwright install chromium
uv run python scripts/generate_marketplace_screenshot.py
uv run python scripts/generate_marketplace_screenshot.py --check
```

Require reviewers to confirm the image is 1440 x 900, both role headings are visible where space permits, the 8 px boundary is obvious, model colors match Model Mix, `Other` is neutral, no tooltip text is clipped, and no personal paths/data appear. Require `git diff -- docs/marketplace/dashboard-synthetic.png` review whenever dashboard presentation changes.

- [ ] **Step 6: Add Unreleased changelog entries without assigning a version**

Add matching bullets under `Unreleased` in both changelogs:

```text
- Split each Project Breakdown row into user-visible root-task and structured-subagent groups, then stacked both groups by model with shared Model Mix colors.
- Kept exact model details while grouping chart models after the largest seven into visual-only Other, with complete accessible tooltips and project role totals.
- Added explicit usage-role persistence through disposable cache schema 5 and rebuilt prior local caches once without rescanning source files for each report view.
- Added a reproducible Playwright-generated Marketplace screenshot and release review gate.
```

Do not change `pyproject.toml`, extension package versions, or dated release headings in this task.

- [ ] **Step 7: Run documentation and history tests**

Run:

```bash
uv run pytest -q tests/test_project_role_model_docs.py tests/test_release_history.py tests/test_parallel_cache_docs.py tests/test_task_transfer_docs.py
```

Expected: all tests pass; new copy is present and historical release text remains unchanged.

- [ ] **Step 8: Commit feature documentation**

```bash
git add README.md extensions/vscode/README.md docs/release.md CHANGELOG.md extensions/vscode/CHANGELOG.md tests/test_project_role_model_docs.py
git commit -m "docs: feature project role and model insights"
```

---

### Task 7: Full Verification, Review, And Native Package Gate

**Files:**
- Modify only files required by concrete verification or review findings.
- Review: all commits from Task 1 through Task 6 against the approved design and ADR 0021.

**Interfaces:**
- Consumes: every prior task interface.
- Produces: a clean review-ready branch with source, browser, macOS package, and cross-platform CI evidence.

- [ ] **Step 1: Run complete Python verification and lint**

```bash
uv run pytest -q
uvx ruff check .
git diff --check
```

Expected: all tests pass, Ruff reports no findings, and whitespace validation prints nothing.

- [ ] **Step 2: Run complete extension verification**

```bash
npm --prefix extensions/vscode test
npm --prefix extensions/vscode run test:registration-smoke
```

Expected: build, TypeScript contract tests, Node tests, and registration smoke all pass. Record existing `npm audit` findings separately; do not broaden this dashboard feature into dependency remediation.

- [ ] **Step 3: Run real-browser screenshot acceptance**

```bash
uv run playwright install chromium
uv run python scripts/generate_marketplace_screenshot.py --check
```

Expected: desktop and narrow viewport checks pass, tooltips remain inside the reserved lane/viewport, role groups have positive in-bounds dimensions, and the generated image passes dimension/color validation.

- [ ] **Step 4: Re-run bounded cache performance acceptance**

```bash
uv run python scripts/parallel_cache_acceptance.py --synthetic
```

Expected: cold parallel usage, warm zero worker spans, one changed-file span, no transition spans, equal semantic digests, and no new source scan caused by report role/model aggregation.

- [ ] **Step 5: Build and smoke the macOS Apple Silicon package**

```bash
npm --prefix extensions/vscode run package:vsix:mac
```

Expected: PyInstaller arm64 binary, packaged parallel-cache smoke, packaged Task Transfer smoke, registration gate, and VSIX creation all pass. Confirm the packaged report displays the role/model chart from synthetic or expendable local data.

- [ ] **Step 6: Request two-stage code review**

Invoke `superpowers:requesting-code-review` with explicit focus on:

- parentless structured subagents misclassified as root tasks;
- schema-4 migration or dual-read code surviving the schema-5 reset;
- range-filtered reports reopening JSONL files or querying cache twice;
- top-seven ordering or `Other` changing by project/input order;
- lost cache-write, unpriced, cost, credit, or event-count fields;
- role gaps distorting complete project width or appearing for one-role projects;
- model colors diverging between Project Breakdown and Model Mix;
- keyboard focus, aria labels, tooltip clipping, narrow viewport overlap, or theme regressions;
- exact Model Details being grouped into `Other`;
- personal data leaking into the tracked Marketplace screenshot;
- Windows/macOS cache path drift or package regressions.

Address confirmed findings with focused tests and commits, then rerun Steps 1 through 5 affected by those changes.

- [ ] **Step 7: Run the native non-publishing GitHub Actions gate after integration**

After the implementation branch is merged into local `main` and pushed at the user's direction, dispatch `Package and Publish VSIX` on that exact `main` commit with `publish=false`. Require both Windows x64 and macOS Apple Silicon jobs to pass before assigning a release version or publishing.

Expected: both native jobs test and package successfully; the macOS job additionally passes the Playwright screenshot renderer gate. Versioning and publication remain a separate explicit release decision.

---

## Plan Completion Criteria

- Every `UsageRecord` has an explicit validated role in memory, JSON output, and schema-5 cache rows.
- Parentless reviews/guardians are subagents; malformed/non-object source markers remain root tasks.
- Project, role, model, token-category, cost, credit, unpriced, and event-count totals conserve.
- Reports perform one project-role-model aggregation over already range-filtered records and no additional source/cache scan.
- Project Breakdown visibly separates role groups and uses the same model identities/colors as Model Mix.
- Project Details exposes root/subagent totals; Model Details remains exact.
- Tooltips and model segments are pointer- and keyboard-accessible in day, night, high-contrast, desktop, and narrow layouts.
- The tracked 1440 x 900 synthetic screenshot is generated from production rendering and passes the Playwright/Pillow gate.
- README, Marketplace, release, and changelog copy feature the capability without weakening Task Transfer or historical release documentation.
- Complete Python, extension, browser, source-performance, macOS package, and dual-native CI gates pass.
