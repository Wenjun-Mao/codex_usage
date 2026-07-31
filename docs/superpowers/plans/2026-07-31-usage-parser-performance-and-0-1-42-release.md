# Usage Parser Performance And 0.1.42 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip JSON decoding for irrelevant Codex events without changing usage totals, then publish the Task Transfer and parser improvements as preview version `0.1.42` on both supported platforms.

**Architecture:** Add a conservative raw-line relevance gate immediately before the existing JSON decoder; all candidate lines still pass through the unchanged structural parser. Keep the SQLite schema, pricing, aggregation, and cache invalidation contracts intact, then version, document, package, tag, and publish the combined performance release.

**Tech Stack:** Python 3.13, pytest, SQLite-backed usage cache, uv, TypeScript/Node tests, PyInstaller, VSCE, GitHub Actions.

## Global Constraints

- Run this plan only after `2026-07-31-task-transfer-metadata-browse.md` is complete and verified.
- Relevant event families are exactly `session_meta`, `turn_context`, `token_count`, and `task_started`.
- The raw-line gate may admit false positives, but must not reject any structurally valid relevant event.
- Every admitted line still uses the existing `json.loads` and structural checks; marker text in user content must not create usage.
- Subagent usage remains included in usage totals.
- Do not change cache schema, pricing, token deltas, fork handling, project transitions, or aggregation semantics.
- Do not implement incremental append checkpoints in this release.
- Release version is exactly `0.1.42`, dated `2026-07-31`.
- Keep `extensions/vscode/package.json` set to Marketplace Preview for `0.1.42`.
- Stable `1.0.0` is blocked until packaged `0.1.42` has been tested manually on macOS Apple Silicon and Windows x64.
- Use `uv` for Python commands and existing npm scripts for extension build/test/package operations.

---

### Task 1: Capture a Pre-Change Parser Equivalence Baseline

**Files:**
- Read only: `src/codex_usage/parser.py`
- Read only: local `~/.codex/sessions/**/*.jsonl`
- Temporary output: `/tmp/codex-usage-parser-baseline.json`
- Temporary fixtures: `/tmp/codex-usage-parser-fixtures/`

**Interfaces:**
- Produces: private, uncommitted copies of up to 100 bounded-size representative files plus deterministic parser-output digests.
- Does not modify: source, tests, cache, or local Codex data.

- [ ] **Step 1: Assert the baseline output is absent**

Run: `rm -rf /tmp/codex-usage-parser-baseline.json /tmp/codex-usage-parser-fixtures && test ! -e /tmp/codex-usage-parser-baseline.json && test ! -e /tmp/codex-usage-parser-fixtures`

Expected: exit code 0.

- [ ] **Step 2: Capture deterministic digests from the existing parser**

Run:

```bash
uv run python - <<'PY'
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from codex_usage.parser import parse_session_file

source_root = Path.home() / ".codex" / "sessions"
fixture_root = Path("/tmp/codex-usage-parser-fixtures")
fixture_root.mkdir()
paths = sorted(
    (path for path in source_root.rglob("*.jsonl") if path.stat().st_size <= 10 * 1024 * 1024),
    key=lambda path: (path.stat().st_size, str(path)),
)
if len(paths) > 100:
    step = (len(paths) - 1) / 99
    paths = [paths[round(index * step)] for index in range(100)]
rows = []
for index, source in enumerate(paths):
    path = fixture_root / f"{index:03d}-{source.name}"
    shutil.copy2(source, path)
    digest = hashlib.sha256(repr(parse_session_file(path)).encode("utf-8")).hexdigest()
    rows.append({"path": str(path), "size_bytes": path.stat().st_size, "digest": digest})
Path("/tmp/codex-usage-parser-baseline.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
print(f"captured={len(rows)} bytes={sum(row['size_bytes'] for row in rows)}")
PY
```

Expected: prints `captured=100` on the measured Mac. If fewer than 100 eligible local files exist, it prints and captures every available file. The 10 MiB per-file cap keeps private temporary evidence bounded; the separate largest-file timing in Task 3 covers multi-gigabyte input.

- [ ] **Step 3: Verify the baseline contains digests but no JSONL contents**

Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

rows = json.loads(Path("/tmp/codex-usage-parser-baseline.json").read_text(encoding="utf-8"))
assert rows
assert all(set(row) == {"path", "size_bytes", "digest"} for row in rows)
assert all(len(row["digest"]) == 64 for row in rows)
print(f"verified={len(rows)}")
PY
```

Expected: prints the verified row count. Keep the digest file and copied fixtures outside Git and delete both after Task 3.

### Task 2: Conservative Raw-Line Relevance Gate

**Files:**
- Modify: `src/codex_usage/parser.py:37-84,150-158`
- Create: `tests/test_parser_relevance_gate.py`

**Interfaces:**
- Produces: `_line_may_affect_usage(raw_line: str) -> bool`.
- Preserves: `parse_session_file(path: Path) -> list[UsageRecord]` output exactly.
- Guarantees: lines with none of the four quoted event markers never reach `json.loads`.

- [ ] **Step 1: Write failing operation-count and semantic tests**

Create `tests/test_parser_relevance_gate.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

import codex_usage.parser as parser_module
from codex_usage.parser import parse_session_file


def _token_count() -> dict[str, object]:
    return {
        "timestamp": "2026-07-31T12:00:03Z",
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": 80,
                    "cached_input_tokens": 20,
                    "output_tokens": 20,
                    "total_tokens": 100,
                }
            },
        },
    }


def test_parser_decodes_only_relevant_candidate_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "session.jsonl"
    relevant = [
        {"timestamp": "2026-07-31T12:00:00Z", "type": "session_meta", "payload": {"id": "session", "cwd": "/repo/demo"}},
        {"timestamp": "2026-07-31T12:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.6-sol", "collaboration_mode": {"mode": "default"}}},
        {"timestamp": "2026-07-31T12:00:02Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1", "collaboration_mode_kind": "default"}},
        _token_count(),
    ]
    lines = [
        json.dumps(relevant[0], separators=(",", ":")),
        json.dumps({"type": "response_item", "payload": {"text": "x" * 2_000_000}}),
        json.dumps(relevant[1], indent=2).replace("\n", " "),
        json.dumps(relevant[2]),
        json.dumps(relevant[3]),
        '{"type":"turn_context", malformed',
        json.dumps({"type": "response_item", "payload": {"token_count": "user content, not an event type"}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    original_loads = parser_module.json.loads
    decoded: list[str] = []

    def counting_loads(value: str) -> object:
        decoded.append(value)
        return original_loads(value)

    monkeypatch.setattr(parser_module.json, "loads", counting_loads)
    records = parse_session_file(path)

    assert len(decoded) == 6
    assert len(records) == 1
    assert records[0].usage.total_tokens == 100
    assert records[0].model == "gpt-5.6-sol"
    assert records[0].turn_id == "turn-1"
    assert records[0].collaboration_mode == "default"


def test_irrelevant_marker_text_cannot_create_usage(tmp_path: Path) -> None:
    path = tmp_path / "misleading.jsonl"
    rows = [
        {"timestamp": "2026-07-31T12:00:00Z", "type": "session_meta", "payload": {"id": "misleading"}},
        {"timestamp": "2026-07-31T12:00:01Z", "type": "response_item", "payload": {"session_meta": "turn_context", "token_count": "task_started"}},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert parse_session_file(path) == []
```

The expected decode count is six: four valid relevant lines, one malformed relevant candidate, and one misleading marker candidate. The 2 MB response line has no marker and must be skipped before decoding.

- [ ] **Step 2: Run the new tests and verify the performance contract fails**

Run: `uv run pytest tests/test_parser_relevance_gate.py -q`

Expected: the decode-count test fails with seven calls because every line is currently decoded.

- [ ] **Step 3: Implement the conservative marker gate**

Add near the top of `parser.py`:

```python
_USAGE_EVENT_MARKERS = (
    '"session_meta"',
    '"turn_context"',
    '"token_count"',
    '"task_started"',
)


def _line_may_affect_usage(raw_line: str) -> bool:
    return any(marker in raw_line for marker in _USAGE_EVENT_MARKERS)
```

Then gate the existing decoder without changing the downstream parser:

```python
with path.open("r", encoding="utf-8") as handle:
    for raw_line in handle:
        if not _line_may_affect_usage(raw_line):
            continue
        obj = _parse_json_line(raw_line)
        if obj is None:
            continue
```

Quoted marker matching is separator- and whitespace-independent because JSON string values remain quoted. A false-positive marker in content only causes the existing structural parser to inspect and reject that line.

- [ ] **Step 4: Run focused parser, fork, model, cache-write, and subagent tests**

Run:

```bash
uv run pytest tests/test_parser_relevance_gate.py tests/test_parser_aggregation.py tests/test_session_provenance.py tests/test_session_cache.py tests/test_pricing.py tests/test_token_usage.py -q
```

Expected: PASS with unchanged token, fork, model, effort, collaboration mode, parent inheritance, and cache-write behavior.

- [ ] **Step 5: Commit the parser gate**

```bash
git add src/codex_usage/parser.py tests/test_parser_relevance_gate.py
git commit -m "perf: skip irrelevant Codex event decoding"
```

### Task 3: Equivalence and Real-Data Performance Acceptance

**Files:**
- Read only: `/tmp/codex-usage-parser-baseline.json`
- Read only: local `~/.codex/sessions/**/*.jsonl`
- Temporary output: `/tmp/codex-usage-7d-performance.html`

**Interfaces:**
- Verifies: parser output remains byte-for-byte equivalent at the `repr(UsageRecord)` level for the sampled files.
- Verifies: the largest local task and dashboard refresh improve materially without a hard CI wall-clock threshold.

- [ ] **Step 1: Recompute and compare all sampled parser digests**

Run:

```bash
uv run python - <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from codex_usage.parser import parse_session_file

baseline_path = Path("/tmp/codex-usage-parser-baseline.json")
baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
mismatches = []
for row in baseline:
    path = Path(row["path"])
    if not path.is_file():
        mismatches.append((str(path), "missing"))
        continue
    digest = hashlib.sha256(repr(parse_session_file(path)).encode("utf-8")).hexdigest()
    if digest != row["digest"]:
        mismatches.append((str(path), digest))
assert not mismatches, mismatches[:5]
print(f"equivalent={len(baseline)}")
PY
```

Expected: prints `equivalent=100` on the measured dataset, or the smaller captured count, with no mismatch.

- [ ] **Step 2: Time the largest active JSONL**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path
from time import perf_counter

from codex_usage.parser import parse_session_file

paths = list((Path.home() / ".codex" / "sessions").rglob("*.jsonl"))
largest = max(paths, key=lambda path: path.stat().st_size)
started = perf_counter()
records = parse_session_file(largest)
elapsed = perf_counter() - started
print({"size_bytes": largest.stat().st_size, "records": len(records), "seconds": round(elapsed, 3)})
PY
```

Expected on the measured Mac: the approximately 2.06 GB representative file parses in roughly 3-5 seconds rather than spending most time decoding irrelevant payloads. Record the observed time in the implementation report, not in a committed machine-specific test.

- [ ] **Step 3: Time a real seven-day dashboard refresh**

Run: `/usr/bin/time -p uv run codex-usage report --range 7d --output /tmp/codex-usage-7d-performance.html`

Expected: completes materially faster than the previously interrupted 108-plus-second run. Confirm the report exists and is nonempty with `test -s /tmp/codex-usage-7d-performance.html`.

- [ ] **Step 4: Delete private temporary evidence**

Run: `rm -rf /tmp/codex-usage-parser-baseline.json /tmp/codex-usage-parser-fixtures /tmp/codex-usage-7d-performance.html`

Expected: neither temporary file remains.

- [ ] **Step 5: Run the complete Python suite**

Run: `uv run pytest -q`

Expected: PASS.

### Task 4: Prepare Preview Version 0.1.42

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `docs/release.md`
- Modify: `tests/test_github_actions_workflow.py`
- Modify: `tests/test_task_transfer_docs.py`
- Modify: `extensions/vscode/test/core.test.js`

**Interfaces:**
- Produces: version `0.1.42` consistently across Python, lock, extension, and extension lock metadata.
- Preserves: `"preview": true` and current Preview headings/copy for this release.
- Documents: root-task visibility, metadata-only browse, parser filtering, and the manual two-platform gate for later `1.0.0`.

- [ ] **Step 1: Update release-contract tests first**

Change version assertions in `tests/test_github_actions_workflow.py` from `0.1.41` to `0.1.42`. Add `"0.1.42": "2026-07-31"` to the dated release expectations in `tests/test_task_transfer_docs.py` and require these changelog bullets:

```python
"Listed only active user-visible root tasks in Task Transfer",
"Deferred complete task hashing and conflict planning until after selection",
"Skipped JSON decoding for irrelevant Codex events without changing usage totals",
```

Keep `extensions/vscode/test/core.test.js` asserting `packageJson.preview === true`, and add a version assertion for `0.1.42`.

- [ ] **Step 2: Run release-contract tests and verify they fail**

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py tests/test_task_transfer_docs.py -q
cd extensions/vscode && npm run build && npm run typecheck:contracts && node --test --test-name-pattern='package metadata' test/core.test.js
```

Expected: FAIL because checked-in versions and changelogs are still `0.1.41`.

- [ ] **Step 3: Bump all package versions mechanically**

Run:

```bash
uv version 0.1.42
uv lock
cd extensions/vscode && npm version 0.1.42 --no-git-tag-version
```

Then verify:

```bash
rg -n 'version = "0\.1\.42"|"version": "0\.1\.42"' pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json
```

Expected: Python project and lock plus both npm version locations report `0.1.42`.

- [ ] **Step 4: Add matching dated changelog entries**

Insert under `Unreleased` in both changelogs:

```markdown
## 0.1.42 - 2026-07-31 - Faster Root-Task Transfer

- Listed only active user-visible root tasks in Task Transfer while keeping subagent usage in dashboard totals.
- Deferred complete task hashing and conflict planning until after selection by replacing browse-time usage parsing and all-task hashing with metadata-only inventory.
- Skipped JSON decoding for irrelevant Codex events without changing usage totals, pricing, cache schema, or aggregation behavior.
```

- [ ] **Step 5: Update current user documentation**

In both READMEs, state that Task Transfer lists active user tasks shown by Codex and intentionally omits internal subagents, guardians, automatic reviews, and archived tasks. State that opening the picker scans metadata and size only, while selected tasks receive full validation before copying. Update the Performance Cache paragraph to explain that changed JSONLs skip irrelevant event decoding but are still reparsed safely from the beginning in this release.

In `docs/release.md`, add these Task Transfer acceptance bullets:

```markdown
- Confirm project counts match user-visible Codex tasks and do not include subagents, guardians, or automatic reviews.
- Confirm opening a large project's task picker completes without hashing every task.
- Confirm selecting one task still runs complete checking before Import, Export, or Review.
```

Add a `## Stable 1.0.0 Promotion Gate` section requiring successful hands-on `0.1.42` validation on packaged macOS Apple Silicon and Windows x64 before removing Preview. List dashboard open/refresh, root-task counts, one export, one import, one review, OneDrive convergence on Windows, and no regression in selected-task conflict checking. Explicitly say historical changelog Preview wording remains unchanged.

- [ ] **Step 6: Run release metadata and documentation tests**

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py tests/test_task_transfer_docs.py -q
cd extensions/vscode && npm test
```

Expected: PASS with version `0.1.42` and `preview: true`.

- [ ] **Step 7: Commit the preview release metadata**

```bash
git add pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json CHANGELOG.md extensions/vscode/CHANGELOG.md README.md extensions/vscode/README.md docs/release.md tests/test_github_actions_workflow.py tests/test_task_transfer_docs.py extensions/vscode/test/core.test.js
git commit -m "chore: prepare 0.1.42 performance release"
```

### Task 5: Full Verification, Merge, Publish, and Stop Before Stable

**Files:**
- Verify: all tracked source, tests, docs, package metadata, and workflows
- Build artifact: `output/releases/codex-usage-dashboard-darwin-arm64.vsix`
- Remote workflow artifacts: Windows x64 and macOS Apple Silicon VSIX packages

**Interfaces:**
- Publishes: Marketplace preview version `0.1.42` for Windows x64 and macOS Apple Silicon.
- Produces: annotated Git tag `v0.1.42` pointing to a commit contained in `origin/main`.
- Stops: no `1.0.0` version bump and no Preview removal in this task.

- [ ] **Step 1: Run complete source suites from a clean dependency state**

Run:

```bash
uv sync --all-groups
uv run pytest -q
cd extensions/vscode
npm ci
npm test
npm run test:registration-smoke
```

Expected: all Python, TypeScript, Node, contract, and registration smoke tests PASS.

- [ ] **Step 2: Build and inspect the macOS Apple Silicon package locally**

Run:

```bash
cd extensions/vscode
npm run package:vsix:mac
test -s ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix
unzip -l ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix | rg 'extension/bin/codex-usage|extension/package.json|extension/README.md'
```

Expected: PyInstaller's packaged Task Transfer smoke passes and the VSIX contains the bundled macOS executable plus extension metadata and README.

- [ ] **Step 3: Verify repository scope and release invariants**

Run:

```bash
git status --short
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
uv run python - <<'PY'
import json
import tomllib
from pathlib import Path

pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
package = json.loads(Path("extensions/vscode/package.json").read_text(encoding="utf-8"))
assert pyproject["project"]["version"] == "0.1.42"
assert package["version"] == "0.1.42"
assert package["preview"] is True
print("release invariants verified")
PY
```

Expected: only intended changes are present, no whitespace errors, all version assertions pass, and Preview remains enabled.

- [ ] **Step 4: Request final code review and address only verified findings**

Invoke `superpowers:requesting-code-review` against the complete branch diff. Review specifically for transfer-root classification, accidental usage filtering, browse-time full reads/hashes, stale inventory protocol fields, path-guard regressions, and parser false negatives. For each finding, use `superpowers:receiving-code-review`, reproduce it with a focused test, make the durable fix, and rerun the affected plus full suites.

Expected: no unresolved correctness findings remain.

- [ ] **Step 5: Integrate to local `main`**

Invoke `superpowers:finishing-a-development-branch`. Merge the implementation branch into local `main` without rewriting unrelated user work, then run:

```bash
git switch main
uv run pytest -q
cd extensions/vscode && npm test
```

Expected: local `main` contains the complete implementation and both suites PASS after merge.

- [ ] **Step 6: Push `main`, tag the release, and trigger publication**

Run:

```bash
git push origin main
git tag -a v0.1.42 -m "v0.1.42 Task Transfer performance release"
git push origin v0.1.42
```

Expected: the tag push triggers exactly one `Package and Publish VSIX` workflow; its tag verification confirms `v0.1.42` matches the extension version and is contained in `origin/main`.

- [ ] **Step 7: Watch the release workflow through Marketplace publication**

Run:

```bash
sha="$(git rev-list -n 1 v0.1.42)"
run_id=""
for attempt in {1..12}; do
  run_id="$(gh run list --workflow package-vsix.yml --commit "$sha" --limit 1 --json databaseId --jq '.[0].databaseId // empty')"
  test -n "$run_id" && break
  sleep 5
done
test -n "$run_id"
gh run watch "$run_id" --exit-status
gh run view "$run_id" --json conclusion,jobs,url
```

Expected: Windows x64 tests/package, macOS Apple Silicon tests/package, and Publish VSIX packages all conclude `success`.

- [ ] **Step 8: Record the manual stable-promotion handoff and stop**

Report the published workflow URL, local performance measurements, root-task counts, and the exact packaged manual checklist from `docs/release.md`. State clearly that `1.0.0` and Preview removal remain blocked until the user confirms hands-on `0.1.42` validation on both supported platforms.

Do not create or push a `v1.0.0` tag in this plan.

## Plan Completion Gate

The preview performance release is complete only when:

- sampled parser digests are unchanged;
- the largest-file and seven-day report checks improve materially;
- subagents remain counted in usage and absent from Task Transfer;
- all Python and VS Code tests pass;
- the macOS package smoke passes locally;
- GitHub's Windows and macOS package jobs pass;
- Marketplace publication succeeds for both VSIX packages; and
- stable promotion remains explicitly pending manual two-platform validation.
