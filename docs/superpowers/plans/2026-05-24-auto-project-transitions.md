# Auto Project Transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically detect high-confidence repository transitions inside Codex threads, split usage at the detected switch timestamp, and show connected project rows without requiring manual JSON settings edits.

**Architecture:** Keep normal project identity resolution in `project_identity.py`, then add a separate transition layer that observes timestamped local repo evidence and rewrites only records after a verified switch point. Summary, report, thread listing, and VS Code all consume the same transition-aware records and include transition metadata for transparency.

**Tech Stack:** Python 3.13 standard library, existing `pydantic-settings`, pytest, TypeScript VS Code wrapper, Node test runner. No network calls and no new runtime dependencies.

---

## File Structure

- Create: `src/codex_usage/project_transitions.py`
  - Owns transition dataclasses, path extraction, read-only Codex evidence scanning, confidence scoring, transition inference, and record rewriting.
- Modify: `src/codex_usage/models.py`
  - Adds transition metadata fields to `UsageRecord` without changing existing JSON fields.
- Modify: `src/codex_usage/settings.py`
  - Adds `auto_project_transitions: bool = True`.
- Modify: `src/codex_usage/cli.py`
  - Adds `transitions suggest --json`.
  - Adds shared `--no-auto-transitions` to `summary`, `report`, and `threads`.
  - Applies inferred transitions after date-independent parsing and before range/project filtering.
- Modify: `src/codex_usage/sync.py`
  - Uses the same transition-aware record flow for thread listing and selected-thread filtering.
- Modify: `src/codex_usage/reporting.py`
  - Adds transition metadata to JSON summaries and HTML report notices.
- Test: `tests/test_project_transitions.py`
  - Unit tests for extraction, scoring, inference, splitting, and no-guess cases.
- Modify: `tests/test_cli.py`, `tests/test_sync.py`, `tests/test_reporting_html.py`
  - CLI, thread, and report integration tests.
- Modify: `extensions/vscode/src/core.ts`
  - Adds transition command builders, settings normalization, parser helpers, and webview command link.
- Modify: `extensions/vscode/src/extension.ts`
  - Adds `Codex Usage: Review Project Transitions` and passes transition settings to the bundled CLI.
- Modify: `extensions/vscode/package.json`
  - Adds command and `codexUsage.projectTransitions.autoDetect` setting.
- Modify: `extensions/vscode/test/core.test.js`
  - Adds tests for args, settings, suggestion parsing, and webview command allowlist.
- Modify: `README.md`, `extensions/vscode/README.md`
  - Documents automatic transitions and review behavior.

---

### Task 1: Add Transition Domain Model And Path Extraction

**Files:**
- Create: `src/codex_usage/project_transitions.py`
- Modify: `src/codex_usage/models.py`
- Test: `tests/test_project_transitions.py`

- [ ] **Step 1: Write failing tests for transition models and path extraction**

Create `tests/test_project_transitions.py` with these tests:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
    extract_windows_paths,
)


def test_extract_windows_paths_from_text() -> None:
    text = (
        "Work in repo `D:\\Work\\repos\\ops-board` and "
        "ignore C:\\Users\\alice\\.codex\\sessions for project identity."
    )

    paths = extract_windows_paths(text)

    assert paths == [
        "D:\\Work\\repos\\ops-board",
        "C:\\Users\\alice\\.codex\\sessions",
    ]


def test_apply_project_transitions_splits_records_at_effective_timestamp(tmp_path: Path) -> None:
    before = UsageRecord(
        timestamp=datetime(2026, 5, 23, 21, 6, 44, tzinfo=UTC),
        usage=TokenUsage(total_tokens=100, input_tokens=100),
        session_id="thread-1",
        file_path=tmp_path / "thread.jsonl",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    after = UsageRecord(
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        usage=TokenUsage(total_tokens=200, input_tokens=200),
        session_id="thread-1",
        file_path=tmp_path / "thread.jsonl",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    transition = ProjectTransition(
        source_key="https://github.com/example/signoz-stack",
        source_label="signoz-stack",
        target_key="https://github.com/example/ops-board",
        target_label="ops-board",
        effective_from=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        confidence=100,
        evidence=("verified local repo path",),
        thread_ids=("thread-1",),
    )

    records = apply_project_transitions([before, after], [transition])

    assert [record.project_key for record in records] == [
        "https://github.com/example/signoz-stack",
        "https://github.com/example/ops-board",
    ]
    assert records[1].project_previous_key == "https://github.com/example/signoz-stack"
    assert records[1].project_transition_effective_from == "2026-05-23T21:06:45+00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: import failure for `codex_usage.project_transitions`.

- [ ] **Step 3: Add transition metadata fields to `UsageRecord`**

In `src/codex_usage/models.py`, extend `UsageRecord` with:

```python
    project_previous_key: str = ""
    project_previous_label: str = ""
    project_transition_effective_from: str = ""
```

In `UsageRecord.to_dict()`, add:

```python
            "project_previous_key": self.project_previous_key,
            "project_previous_label": self.project_previous_label,
            "project_transition_effective_from": self.project_transition_effective_from,
```

- [ ] **Step 4: Add minimal transition module implementation**

Create `src/codex_usage/project_transitions.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime

from codex_usage.models import UsageRecord


_WINDOWS_PATH_PATTERN = re.compile(r"[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n`]+\\)*[^\\/:*?\"<>|\r\n`]+")


@dataclass(frozen=True)
class ProjectTransition:
    source_key: str
    source_label: str
    target_key: str
    target_label: str
    effective_from: datetime
    confidence: int
    evidence: tuple[str, ...] = ()
    thread_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_key": self.source_key,
            "source_label": self.source_label,
            "target_key": self.target_key,
            "target_label": self.target_label,
            "effective_from": self.effective_from.isoformat(),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "thread_ids": list(self.thread_ids),
        }


def extract_windows_paths(text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for match in _WINDOWS_PATH_PATTERN.finditer(text):
        value = match.group(0).rstrip(".,;:)]}'\"")
        if value and value not in seen:
            seen.add(value)
            paths.append(value)
    return paths


def apply_project_transitions(
    records: list[UsageRecord],
    transitions: list[ProjectTransition],
) -> list[UsageRecord]:
    if not transitions:
        return records

    ordered = sorted(transitions, key=lambda item: item.effective_from)
    rewritten: list[UsageRecord] = []
    for record in records:
        applied = None
        for transition in ordered:
            if record.project_key == transition.source_key and record.timestamp >= transition.effective_from:
                applied = transition
        if applied is None:
            rewritten.append(record)
            continue
        aliases = _dedupe_aliases([record.project_key, *record.project_aliases], applied.target_key)
        rewritten.append(
            replace(
                record,
                project_key=applied.target_key,
                project_label=applied.target_label,
                project_aliases=aliases,
                project_previous_key=applied.source_key,
                project_previous_label=applied.source_label,
                project_transition_effective_from=applied.effective_from.isoformat(),
            )
        )
    return rewritten


def _dedupe_aliases(values: list[str], primary_key: str) -> tuple[str, ...]:
    aliases: list[str] = []
    seen = {primary_key}
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        aliases.append(value)
    return tuple(aliases)
```

- [ ] **Step 5: Run tests to verify Task 1 passes**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add src/codex_usage/models.py src/codex_usage/project_transitions.py tests/test_project_transitions.py
git commit -m "feat: add project transition model"
```

Expected: commit succeeds.

---

### Task 2: Add Verified Repo Path Observations

**Files:**
- Modify: `src/codex_usage/project_transitions.py`
- Test: `tests/test_project_transitions.py`

- [ ] **Step 1: Add failing tests for Git-origin verified path observations**

Append to `tests/test_project_transitions.py`:

```python
from codex_usage.project_transitions import verified_repo_observation_from_path


def test_verified_repo_observation_from_path_resolves_git_origin(tmp_path: Path) -> None:
    repo = tmp_path / "ops-board"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/Wenjun-Mao/ops-board.git\n',
        encoding="utf-8",
    )

    observation = verified_repo_observation_from_path(
        raw_path=str(repo),
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="jsonl:function_call_output",
    )

    assert observation is not None
    assert observation.project_key == "https://github.com/wenjun-mao/ops-board"
    assert observation.project_label == "ops-board"
    assert observation.thread_id == "thread-1"
    assert observation.source == "jsonl:function_call_output"


def test_verified_repo_observation_returns_none_for_missing_path(tmp_path: Path) -> None:
    observation = verified_repo_observation_from_path(
        raw_path=str(tmp_path / "missing"),
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="jsonl:message",
    )

    assert observation is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: import failure for `verified_repo_observation_from_path`.

- [ ] **Step 3: Add observation dataclass and path verification**

In `src/codex_usage/project_transitions.py`, add imports:

```python
from pathlib import Path

from codex_usage.project_identity import normalize_project_key
```

Add:

```python
@dataclass(frozen=True)
class RepoPathObservation:
    raw_path: str
    resolved_path: str
    project_key: str
    project_label: str
    timestamp: datetime
    thread_id: str
    source: str

    def to_evidence_text(self) -> str:
        return f"{self.source} references {self.resolved_path}, resolved to {self.project_key}"


def verified_repo_observation_from_path(
    *,
    raw_path: str,
    timestamp: datetime,
    thread_id: str,
    source: str,
) -> RepoPathObservation | None:
    path = Path(raw_path).expanduser()
    if not path.exists():
        return None
    project_key = normalize_project_key(str(path))
    if not project_key.startswith("https://"):
        return None
    return RepoPathObservation(
        raw_path=raw_path,
        resolved_path=str(path),
        project_key=project_key,
        project_label=_label_from_project_key(project_key),
        timestamp=timestamp,
        thread_id=thread_id,
        source=source,
    )


def _label_from_project_key(value: str) -> str:
    cleaned = value.rstrip("/").removesuffix(".git")
    return cleaned.rsplit("/", 1)[-1] or cleaned
```

- [ ] **Step 4: Run tests to verify Task 2 passes**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add src/codex_usage/project_transitions.py tests/test_project_transitions.py
git commit -m "feat: verify repo path observations"
```

Expected: commit succeeds.

---

### Task 3: Scan Codex Evidence For Timestamped Repo Observations

**Files:**
- Modify: `src/codex_usage/project_transitions.py`
- Test: `tests/test_project_transitions.py`

- [ ] **Step 1: Add failing tests for JSONL and SQLite evidence scanning**

Append to `tests/test_project_transitions.py`:

```python
import sqlite3

from codex_usage.project_transitions import collect_repo_path_observations


def test_collect_repo_path_observations_reads_jsonl_timestamped_path(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "rollout-2026-05-23T17-00-00-thread-1.jsonl"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:00Z",
                        "type": "session_meta",
                        "payload": {"id": "thread-1", "cwd": "D:\\old\\signoz-stack"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:45Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "output": f"repo path is {repo}",
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])

    assert len(observations) == 1
    assert observations[0].thread_id == "thread-1"
    assert observations[0].project_key == "https://github.com/wenjun-mao/ops-board"
    assert observations[0].timestamp == datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)


def test_collect_repo_path_observations_reads_state_sqlite_thread_prompt(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    repo = tmp_path / "ops-board"
    _write_git_config(repo, "https://github.com/Wenjun-Mao/ops-board.git")
    con = sqlite3.connect(codex_home / "state_5.sqlite")
    try:
        con.execute(
            "create table threads (id text primary key, created_at integer, updated_at integer, cwd text, title text, first_user_message text, preview text)"
        )
        con.execute(
            "insert into threads values (?, ?, ?, ?, ?, ?, ?)",
            (
                "thread-1",
                1779570405000,
                1779570405000,
                str(repo),
                "Task in ops-board",
                f"Work in repo `{repo}`",
                "",
            ),
        )
        con.commit()
    finally:
        con.close()

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[])

    assert len(observations) == 1
    assert observations[0].thread_id == "thread-1"
    assert observations[0].project_key == "https://github.com/wenjun-mao/ops-board"


def _write_git_config(repo: Path, url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: import failure for `collect_repo_path_observations`.

- [ ] **Step 3: Implement evidence scanning**

In `src/codex_usage/project_transitions.py`, add imports:

```python
import json
import sqlite3
from typing import Any

from codex_usage.parser import parse_timestamp
```

Add these functions:

```python
def collect_repo_path_observations(
    *,
    session_dirs: list[Path],
    session_files: list[Path],
) -> list[RepoPathObservation]:
    observations: list[RepoPathObservation] = []
    observations.extend(_collect_jsonl_observations(session_files))
    observations.extend(_collect_state_sqlite_observations(session_dirs))
    return _dedupe_observations(observations)


def _collect_jsonl_observations(session_files: list[Path]) -> list[RepoPathObservation]:
    observations: list[RepoPathObservation] = []
    for path in session_files:
        current_thread_id = path.stem
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                obj = _parse_json_line(line)
                if obj is None:
                    continue
                timestamp = parse_timestamp(obj.get("timestamp"))
                if timestamp is None:
                    continue
                payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                if obj.get("type") == "session_meta":
                    current_thread_id = _thread_id_from_payload(payload) or current_thread_id
                text = _event_text(obj)
                if not text:
                    continue
                for raw_path in extract_windows_paths(text):
                    observation = verified_repo_observation_from_path(
                        raw_path=raw_path,
                        timestamp=timestamp,
                        thread_id=current_thread_id,
                        source=f"jsonl:{obj.get('type') or 'event'}",
                    )
                    if observation is not None:
                        observations.append(observation)
    return observations


def _collect_state_sqlite_observations(session_dirs: list[Path]) -> list[RepoPathObservation]:
    observations: list[RepoPathObservation] = []
    for session_dir in session_dirs:
        db_path = _codex_home_from_session_dir(session_dir) / "state_5.sqlite"
        if not db_path.is_file():
            continue
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "select id, created_at, created_at_ms, cwd, title, first_user_message, preview from threads"
                ).fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        for thread_id, created_at, created_at_ms, cwd, title, first_user_message, preview in rows:
            timestamp = _sqlite_timestamp(created_at_ms or created_at)
            text = " ".join(str(value or "") for value in (cwd, title, first_user_message, preview))
            for raw_path in extract_windows_paths(text):
                observation = verified_repo_observation_from_path(
                    raw_path=raw_path,
                    timestamp=timestamp,
                    thread_id=str(thread_id),
                    source="state_5.sqlite:threads",
                )
                if observation is not None:
                    observations.append(observation)
    return observations


def _event_text(obj: dict[str, Any]) -> str:
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    values: list[str] = []
    for key in ("message", "output", "stdout", "stderr", "last_agent_message"):
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
    content = payload.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                values.append(part["text"])
    return "\n".join(values)


def _thread_id_from_payload(payload: dict[str, Any]) -> str:
    return str(payload.get("id") or "")


def _sqlite_timestamp(value: object) -> datetime:
    parsed = parse_timestamp(value)
    if parsed is None:
        return datetime.fromtimestamp(0, tz=datetime.now().astimezone().tzinfo)
    return parsed


def _parse_json_line(line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _codex_home_from_session_dir(session_dir: Path) -> Path:
    return session_dir.parent if session_dir.name.casefold() == "sessions" else session_dir.parent


def _dedupe_observations(observations: list[RepoPathObservation]) -> list[RepoPathObservation]:
    unique: list[RepoPathObservation] = []
    seen: set[tuple[str, str, str, datetime]] = set()
    for observation in observations:
        key = (observation.thread_id, observation.project_key, observation.resolved_path, observation.timestamp)
        if key in seen:
            continue
        seen.add(key)
        unique.append(observation)
    return sorted(unique, key=lambda item: item.timestamp)
```

- [ ] **Step 4: Run tests to verify Task 3 passes**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add src/codex_usage/project_transitions.py tests/test_project_transitions.py
git commit -m "feat: scan codex evidence for repo paths"
```

Expected: commit succeeds.

---

### Task 4: Infer High-Confidence Transitions

**Files:**
- Modify: `src/codex_usage/project_transitions.py`
- Test: `tests/test_project_transitions.py`

- [ ] **Step 1: Add failing inference tests**

Append to `tests/test_project_transitions.py`:

```python
from codex_usage.project_transitions import RepoPathObservation, infer_project_transitions


def test_infer_project_transitions_uses_first_verified_new_repo_after_old_usage(tmp_path: Path) -> None:
    records = [
        UsageRecord(
            timestamp=datetime(2026, 5, 23, 21, 0, 0, tzinfo=UTC),
            usage=TokenUsage(total_tokens=100, input_tokens=100),
            session_id="thread-1",
            file_path=tmp_path / "thread.jsonl",
            project_key="https://github.com/example/signoz-stack",
            project_label="signoz-stack",
        ),
        UsageRecord(
            timestamp=datetime(2026, 5, 23, 21, 7, 0, tzinfo=UTC),
            usage=TokenUsage(total_tokens=200, input_tokens=200),
            session_id="thread-1",
            file_path=tmp_path / "thread.jsonl",
            project_key="https://github.com/example/signoz-stack",
            project_label="signoz-stack",
        ),
    ]
    observations = [
        RepoPathObservation(
            raw_path="D:\\Projects\\ops-board",
            resolved_path="D:\\Projects\\ops-board",
            project_key="https://github.com/example/ops-board",
            project_label="ops-board",
            timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
            thread_id="thread-1",
            source="jsonl:function_call_output",
        )
    ]

    transitions = infer_project_transitions(records, observations)

    assert len(transitions) == 1
    assert transitions[0].source_key == "https://github.com/example/signoz-stack"
    assert transitions[0].target_key == "https://github.com/example/ops-board"
    assert transitions[0].effective_from == datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)
    assert transitions[0].confidence >= 90


def test_infer_project_transitions_ignores_same_project_observation(tmp_path: Path) -> None:
    record = UsageRecord(
        timestamp=datetime(2026, 5, 23, 21, 0, 0, tzinfo=UTC),
        usage=TokenUsage(total_tokens=100, input_tokens=100),
        session_id="thread-1",
        file_path=tmp_path / "thread.jsonl",
        project_key="https://github.com/example/demo",
        project_label="demo",
    )
    observation = RepoPathObservation(
        raw_path="D:\\Projects\\demo",
        resolved_path="D:\\Projects\\demo",
        project_key="https://github.com/example/demo",
        project_label="demo",
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="jsonl:function_call_output",
    )

    assert infer_project_transitions([record], [observation]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: import failure for `infer_project_transitions`.

- [ ] **Step 3: Implement high-confidence inference**

In `src/codex_usage/project_transitions.py`, add:

```python
def infer_project_transitions(
    records: list[UsageRecord],
    observations: list[RepoPathObservation],
    *,
    minimum_confidence: int = 90,
) -> list[ProjectTransition]:
    records_by_thread: dict[str, list[UsageRecord]] = {}
    for record in records:
        records_by_thread.setdefault(record.session_id, []).append(record)

    candidates: list[ProjectTransition] = []
    for observation in observations:
        thread_records = sorted(records_by_thread.get(observation.thread_id, []), key=lambda item: item.timestamp)
        if not thread_records:
            continue
        source = _source_record_before_observation(thread_records, observation)
        if source is None or source.project_key == observation.project_key:
            continue
        confidence = _transition_confidence(source, observation, thread_records)
        if confidence < minimum_confidence:
            continue
        candidates.append(
            ProjectTransition(
                source_key=source.project_key,
                source_label=source.project_label,
                target_key=observation.project_key,
                target_label=observation.project_label,
                effective_from=observation.timestamp,
                confidence=confidence,
                evidence=(observation.to_evidence_text(),),
                thread_ids=(observation.thread_id,),
            )
        )
    return _dedupe_transitions(candidates)


def _source_record_before_observation(
    records: list[UsageRecord],
    observation: RepoPathObservation,
) -> UsageRecord | None:
    previous = [record for record in records if record.timestamp < observation.timestamp]
    if previous:
        return previous[-1]
    return records[0] if records else None


def _transition_confidence(
    source: UsageRecord,
    observation: RepoPathObservation,
    thread_records: list[UsageRecord],
) -> int:
    score = 70
    if observation.source.startswith("jsonl:") or observation.source.startswith("state_5.sqlite"):
        score += 25
    if any(record.timestamp < observation.timestamp for record in thread_records):
        score += 20
    if _repo_owner(source.project_key) and _repo_owner(source.project_key) == _repo_owner(observation.project_key):
        score += 10
    return min(score, 100)


def _repo_owner(project_key: str) -> str:
    parts = project_key.rstrip("/").split("/")
    if len(parts) < 2:
        return ""
    return parts[-2]


def _dedupe_transitions(transitions: list[ProjectTransition]) -> list[ProjectTransition]:
    by_key: dict[tuple[str, str], ProjectTransition] = {}
    for transition in sorted(transitions, key=lambda item: (-item.confidence, item.effective_from)):
        key = (transition.source_key, transition.target_key)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = transition
            continue
        evidence = tuple(dict.fromkeys([*existing.evidence, *transition.evidence]))
        thread_ids = tuple(dict.fromkeys([*existing.thread_ids, *transition.thread_ids]))
        by_key[key] = ProjectTransition(
            source_key=existing.source_key,
            source_label=existing.source_label,
            target_key=existing.target_key,
            target_label=existing.target_label,
            effective_from=min(existing.effective_from, transition.effective_from),
            confidence=max(existing.confidence, transition.confidence),
            evidence=evidence,
            thread_ids=thread_ids,
        )
    return sorted(by_key.values(), key=lambda item: item.effective_from)
```

- [ ] **Step 4: Run tests to verify Task 4 passes**

Run:

```powershell
uv run pytest tests/test_project_transitions.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add src/codex_usage/project_transitions.py tests/test_project_transitions.py
git commit -m "feat: infer high-confidence project transitions"
```

Expected: commit succeeds.

---

### Task 5: Apply Transitions In CLI Summaries And Reports

**Files:**
- Modify: `src/codex_usage/settings.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `src/codex_usage/reporting.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_cli_auto_project_transitions_split_project_usage(tmp_path: Path, monkeypatch, capsys) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    old_repo = tmp_path / "signoz-stack"
    new_repo = tmp_path / "ops-board"
    _write_git_config(new_repo, "https://github.com/example/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "rollout-2026-05-23T17-00-00-thread-1.jsonl"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-1",
                            "cwd": str(old_repo),
                            "git": {"repository_url": "https://github.com/example/signoz-stack.git"},
                        },
                    }
                ),
                json.dumps({"timestamp": "2026-05-23T21:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}}),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:02Z",
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"total_token_usage": _usage(total=100)}},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:45Z",
                        "type": "response_item",
                        "payload": {"type": "function_call_output", "output": f"Path {new_repo}"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:46Z",
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"total_token_usage": _usage(total=300)}},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_USAGE_SESSIONS_DIR", str(sessions))

    assert main(["summary", "--range", "all", "--by", "project", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert {row["key"]: row["usage"]["total_tokens"] for row in payload["rows"]} == {
        "https://github.com/example/ops-board": 200,
        "https://github.com/example/signoz-stack": 100,
    }
    assert payload["project_transitions"][0]["source_key"] == "https://github.com/example/signoz-stack"
    assert payload["project_transitions"][0]["target_key"] == "https://github.com/example/ops-board"


def test_cli_no_auto_project_transitions_keeps_original_project(tmp_path: Path, monkeypatch, capsys) -> None:
    # Reuse the same fixture shape from test_cli_auto_project_transitions_split_project_usage.
    # This test intentionally asserts the opt-out behavior for users who distrust automatic splitting.
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    old_repo = tmp_path / "signoz-stack"
    new_repo = tmp_path / "ops-board"
    _write_git_config(new_repo, "https://github.com/example/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "rollout-2026-05-23T17-00-00-thread-1.jsonl"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-1",
                            "cwd": str(old_repo),
                            "git": {"repository_url": "https://github.com/example/signoz-stack.git"},
                        },
                    }
                ),
                json.dumps({"timestamp": "2026-05-23T21:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}}),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:02Z",
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"total_token_usage": _usage(total=100)}},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:45Z",
                        "type": "response_item",
                        "payload": {"type": "function_call_output", "output": f"Path {new_repo}"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:46Z",
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"total_token_usage": _usage(total=300)}},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_USAGE_SESSIONS_DIR", str(sessions))

    assert main(["summary", "--range", "all", "--by", "project", "--json", "--no-auto-transitions"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert {row["key"]: row["usage"]["total_tokens"] for row in payload["rows"]} == {
        "https://github.com/example/signoz-stack": 300,
    }
    assert payload["project_transitions"] == []
```

If `tests/test_cli.py` does not already import `json`, `Path`, `main`, or `_usage`, add or reuse the existing local helpers in that file rather than duplicating incompatible helper signatures.

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```powershell
uv run pytest tests/test_cli.py -q
```

Expected: parser error for unknown `--no-auto-transitions` or missing `project_transitions`.

- [ ] **Step 3: Add setting and CLI flag**

In `src/codex_usage/settings.py`, add:

```python
    auto_project_transitions: bool = True
```

In `src/codex_usage/cli.py`, update `_add_common_options()`:

```python
    parser.add_argument(
        "--no-auto-transitions",
        action="store_true",
        help="Disable automatic high-confidence project transition detection.",
    )
```

- [ ] **Step 4: Apply transitions in `_load_context()`**

In `src/codex_usage/cli.py`, import:

```python
from codex_usage.project_transitions import (
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
```

Extend `_Context.__init__` with `project_transitions`:

```python
        project_transitions,
```

and set:

```python
        self.project_transitions = project_transitions
```

In `_load_context()`, after `records = parse_session_files(files)`, add:

```python
    project_transitions = []
    auto_transitions = settings.auto_project_transitions and not getattr(args, "no_auto_transitions", False)
    if auto_transitions:
        observations = collect_repo_path_observations(session_dirs=session_dirs, session_files=files)
        project_transitions = infer_project_transitions(records, observations)
        records = apply_project_transitions(records, project_transitions)
```

Pass `project_transitions=project_transitions` into `_Context(...)`.

- [ ] **Step 5: Add transition metadata to summary/report payloads**

In `src/codex_usage/reporting.py`, add optional parameter `project_transitions` to `summary_payload()` and `render_html_report()`.

In `summary_payload()`, add:

```python
        "project_transitions": [transition.to_dict() for transition in project_transitions or []],
```

In `src/codex_usage/cli.py`, pass `context.project_transitions` to both `summary_payload()` and `render_html_report()`.

- [ ] **Step 6: Run CLI tests to verify Task 5 passes**

Run:

```powershell
uv run pytest tests/test_cli.py tests/test_project_transitions.py -q
```

Expected: tests pass.

- [ ] **Step 7: Commit Task 5**

Run:

```powershell
git add src/codex_usage/settings.py src/codex_usage/cli.py src/codex_usage/reporting.py tests/test_cli.py
git commit -m "feat: apply automatic project transitions"
```

Expected: commit succeeds.

---

### Task 6: Add Transition Suggest CLI

**Files:**
- Modify: `src/codex_usage/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add failing CLI smoke test**

Append to `tests/test_cli.py`:

```python
def test_cli_transitions_suggest_json(tmp_path: Path, monkeypatch, capsys) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    old_repo = tmp_path / "signoz-stack"
    new_repo = tmp_path / "ops-board"
    _write_git_config(new_repo, "https://github.com/example/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "rollout-2026-05-23T17-00-00-thread-1.jsonl"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-1",
                            "cwd": str(old_repo),
                            "git": {"repository_url": "https://github.com/example/signoz-stack.git"},
                        },
                    }
                ),
                json.dumps({"timestamp": "2026-05-23T21:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}}),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:02Z",
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"total_token_usage": _usage(total=100)}},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:45Z",
                        "type": "response_item",
                        "payload": {"type": "function_call_output", "output": f"Path {new_repo}"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_USAGE_SESSIONS_DIR", str(sessions))

    assert main(["transitions", "suggest", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["project_transitions"][0]["source_key"] == "https://github.com/example/signoz-stack"
    assert payload["project_transitions"][0]["target_key"] == "https://github.com/example/ops-board"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run pytest tests/test_cli.py::test_cli_transitions_suggest_json -q
```

Expected: argparse failure for missing `transitions` command.

- [ ] **Step 3: Add CLI command**

In `src/codex_usage/cli.py`, add to `build_parser()`:

```python
    transitions_parser = subparsers.add_parser("transitions", help="Inspect inferred project transitions.")
    transitions_subparsers = transitions_parser.add_subparsers(dest="transitions_command")

    suggest_parser = transitions_subparsers.add_parser("suggest", help="Suggest high-confidence project transitions.")
    _add_common_options(suggest_parser)
    suggest_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    suggest_parser.set_defaults(handler=handle_transitions_suggest)
```

Add handler:

```python
def handle_transitions_suggest(args: argparse.Namespace) -> int:
    settings = get_settings()
    session_dirs = find_session_dirs(args.sessions_dir, settings)
    files = collect_jsonl_files(session_dirs)
    records = parse_session_files(files)
    observations = collect_repo_path_observations(session_dirs=session_dirs, session_files=files)
    transitions = infer_project_transitions(records, observations)
    payload = {
        "project_transitions": [transition.to_dict() for transition in transitions],
        "files_scanned": len(files),
        "sessions_dirs": [str(path) for path in session_dirs],
    }
    if args.json:
        print_json(payload)
    else:
        for transition in transitions:
            print(f"{transition.source_label} -> {transition.target_label}\t{transition.effective_from.isoformat()}\t{transition.confidence}")
    return 0
```

- [ ] **Step 4: Run test to verify Task 6 passes**

Run:

```powershell
uv run pytest tests/test_cli.py::test_cli_transitions_suggest_json -q
```

Expected: test passes.

- [ ] **Step 5: Commit Task 6**

Run:

```powershell
git add src/codex_usage/cli.py tests/test_cli.py
git commit -m "feat: add project transition suggestions cli"
```

Expected: commit succeeds.

---

### Task 7: Show Connected Projects In Reports

**Files:**
- Modify: `src/codex_usage/reporting.py`
- Test: `tests/test_reporting_html.py`

- [ ] **Step 1: Add failing report test**

Append to `tests/test_reporting_html.py`:

```python
from datetime import UTC, datetime

from codex_usage.project_transitions import ProjectTransition


def test_report_shows_project_transition_notice(tmp_path: Path) -> None:
    output = tmp_path / "report.html"
    transition = ProjectTransition(
        source_key="https://github.com/example/signoz-stack",
        source_label="signoz-stack",
        target_key="https://github.com/example/ops-board",
        target_label="ops-board",
        effective_from=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        confidence=100,
        evidence=("verified local repo path",),
        thread_ids=("thread-1",),
    )

    render_html_report(
        output_path=output,
        generated_at=datetime(2026, 5, 23, 21, 10, tzinfo=UTC),
        range_name="all",
        total=_summary(total=300),
        daily_rows=[],
        hourly_rows=[],
        project_rows=[],
        model_rows=[],
        sessions_dirs=[tmp_path],
        files_scanned=1,
        project_transitions=[transition],
    )

    html = output.read_text(encoding="utf-8")

    assert "Project Transitions" in html
    assert "signoz-stack" in html
    assert "ops-board" in html
    assert "2026-05-23T21:06:45+00:00" in html
```

Use existing helper names in `tests/test_reporting_html.py`; if `_summary` has a different signature, adapt this test to the existing helper rather than creating conflicting helper functions.

- [ ] **Step 2: Run report test to verify it fails**

Run:

```powershell
uv run pytest tests/test_reporting_html.py::test_report_shows_project_transition_notice -q
```

Expected: assertion failure because report does not render transition notice.

- [ ] **Step 3: Render project transition section**

In `src/codex_usage/reporting.py`, add a helper:

```python
def _project_transition_section(project_transitions) -> str:
    transitions = list(project_transitions or [])
    if not transitions:
        return ""
    rows = "\n".join(
        "<tr>"
        f"<td>{escape_html(item.source_label)}</td>"
        f"<td>{escape_html(item.target_label)}</td>"
        f"<td>{escape_html(item.effective_from.isoformat())}</td>"
        f"<td>{item.confidence}</td>"
        "</tr>"
        for item in transitions
    )
    return (
        '<section class="section">'
        "<h2>Project Transitions</h2>"
        "<p>Usage is split at verified local repository switch points.</p>"
        "<table>"
        "<thead><tr><th>From</th><th>To</th><th>Effective From</th><th>Confidence</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</section>"
    )
```

Call this helper after the KPI/notices area and before exact tables:

```python
    transition_html = _project_transition_section(project_transitions)
```

and include `{transition_html}` in the HTML body.

- [ ] **Step 4: Run report test to verify Task 7 passes**

Run:

```powershell
uv run pytest tests/test_reporting_html.py::test_report_shows_project_transition_notice -q
```

Expected: test passes.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git add src/codex_usage/reporting.py tests/test_reporting_html.py
git commit -m "feat: show project transitions in reports"
```

Expected: commit succeeds.

---

### Task 8: Make Threads And Sync Transition-Aware

**Files:**
- Modify: `src/codex_usage/sync.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Add failing sync thread listing test**

Append to `tests/test_sync.py`:

```python
def test_list_threads_filters_by_transition_target_project(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    old_repo = tmp_path / "signoz-stack"
    new_repo = tmp_path / "ops-board"
    _write_git_config(new_repo, "https://github.com/example/ops-board.git")
    day = sessions / "2026" / "05" / "23"
    day.mkdir(parents=True)
    path = day / "rollout-2026-05-23T17-00-00-thread-1.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-1",
                            "cwd": str(old_repo),
                            "git": {"repository_url": "https://github.com/example/signoz-stack.git"},
                        },
                    }
                ),
                json.dumps({"timestamp": "2026-05-23T21:00:01Z", "type": "turn_context", "payload": {"model": "gpt-5.5"}}),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:00:02Z",
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 100, "input_tokens": 100}}},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:45Z",
                        "type": "response_item",
                        "payload": {"type": "function_call_output", "output": f"Path {new_repo}"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-05-23T21:06:46Z",
                        "type": "event_msg",
                        "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 300, "input_tokens": 300}}},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    _write_index(codex_home, {"id": "thread-1", "thread_name": "Ops thread", "updated_at": "2026-05-23T21:07:00Z"})

    threads = list_threads([sessions], project_keys=["https://github.com/example/ops-board"])

    assert [thread.thread_id for thread in threads] == ["thread-1"]
    assert threads[0].project_key == "https://github.com/example/ops-board"
```

- [ ] **Step 2: Run sync test to verify it fails**

Run:

```powershell
uv run pytest tests/test_sync.py::test_list_threads_filters_by_transition_target_project -q
```

Expected: no matching thread or wrong project key.

- [ ] **Step 3: Apply transition inference in `list_threads()`**

In `src/codex_usage/sync.py`, import:

```python
from codex_usage.project_transitions import (
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)
```

In `list_threads()`, after `records_by_path` is initially populated from `parse_session_files(session_paths)`, replace that population with:

```python
    parsed_records = parse_session_files(session_paths)
    observations = collect_repo_path_observations(session_dirs=session_dirs, session_files=session_paths)
    transitions = infer_project_transitions(parsed_records, observations)
    parsed_records = apply_project_transitions(parsed_records, transitions)
    records_by_path: dict[Path, list[UsageRecord]] = {}
    for record in parsed_records:
        records_by_path.setdefault(record.file_path, []).append(record)
```

- [ ] **Step 4: Run sync test to verify Task 8 passes**

Run:

```powershell
uv run pytest tests/test_sync.py::test_list_threads_filters_by_transition_target_project -q
```

Expected: test passes.

- [ ] **Step 5: Commit Task 8**

Run:

```powershell
git add src/codex_usage/sync.py tests/test_sync.py
git commit -m "feat: make thread listing transition aware"
```

Expected: commit succeeds.

---

### Task 9: Add VS Code Transition Review Command

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/package.json`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add failing TypeScript tests**

Append to `extensions/vscode/test/core.test.js`:

```javascript
test("transition suggestion args and parser support review command", () => {
  const args = buildTransitionSuggestArgs({ sessionsDir: "C:/codex/sessions" });
  assert.deepEqual(args, ["transitions", "suggest", "--json", "--sessions-dir", "C:/codex/sessions"]);

  const choices = parseTransitionChoices(
    JSON.stringify({
      project_transitions: [
        {
          source_key: "https://github.com/example/signoz-stack",
          source_label: "signoz-stack",
          target_key: "https://github.com/example/ops-board",
          target_label: "ops-board",
          effective_from: "2026-05-23T21:06:45+00:00",
          confidence: 100,
          evidence: ["verified local repo path"],
          thread_ids: ["thread-1"],
        },
      ],
    }),
  );

  assert.equal(choices.length, 1);
  assert.equal(choices[0].label, "signoz-stack -> ops-board");
  assert.match(choices[0].description, /100/);
  assert.equal(choices[0].transition.target_key, "https://github.com/example/ops-board");
});

test("webview command allowlist includes project transition review", () => {
  assert.ok(WEBVIEW_COMMANDS.includes("codexUsage.reviewProjectTransitions"));
});
```

Update the destructuring import at the top of `core.test.js` to include `buildTransitionSuggestArgs` and `parseTransitionChoices`.

- [ ] **Step 2: Run TypeScript tests to verify they fail**

Run:

```powershell
cd extensions/vscode
npm test
```

Expected: missing exported functions.

- [ ] **Step 3: Add core helpers**

In `extensions/vscode/src/core.ts`, add `codexUsage.reviewProjectTransitions` to `WEBVIEW_COMMANDS`.

Add types and helpers:

```typescript
export type TransitionSuggestCommandOptions = {
  sessionsDir?: string;
};

export type TransitionChoice = {
  label: string;
  description: string;
  detail: string;
  picked: boolean;
  transition: {
    source_key: string;
    target_key: string;
    source_label: string;
    target_label: string;
    effective_from: string;
    confidence: number;
  };
};

export function buildTransitionSuggestArgs(options: TransitionSuggestCommandOptions): string[] {
  const args = ["transitions", "suggest", "--json"];
  appendCommonArgs(args, options);
  return args;
}

export function parseTransitionChoices(transitionsJson: string): TransitionChoice[] {
  let payload: unknown;
  try {
    payload = JSON.parse(transitionsJson);
  } catch (error) {
    throw new Error(`Could not parse Codex transition JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  const rows = isRecord(payload) && Array.isArray(payload.project_transitions) ? payload.project_transitions : [];
  const choices: TransitionChoice[] = [];
  for (const row of rows) {
    if (!isRecord(row) || typeof row.source_key !== "string" || typeof row.target_key !== "string") {
      continue;
    }
    const sourceLabel = typeof row.source_label === "string" && row.source_label ? row.source_label : row.source_key;
    const targetLabel = typeof row.target_label === "string" && row.target_label ? row.target_label : row.target_key;
    const confidence = numberValue(row.confidence);
    const effectiveFrom = typeof row.effective_from === "string" ? row.effective_from : "";
    choices.push({
      label: `${sourceLabel} -> ${targetLabel}`,
      description: `confidence ${confidence}`,
      detail: effectiveFrom,
      picked: true,
      transition: {
        source_key: row.source_key,
        target_key: row.target_key,
        source_label: sourceLabel,
        target_label: targetLabel,
        effective_from: effectiveFrom,
        confidence,
      },
    });
  }
  return choices;
}
```

In `renderWebviewControls()`, add:

```typescript
    '<a href="command:codexUsage.reviewProjectTransitions">Transitions</a>' +
```

- [ ] **Step 4: Add package command and setting**

In `extensions/vscode/package.json`, add activation event:

```json
"onCommand:codexUsage.reviewProjectTransitions"
```

Add command:

```json
{
  "command": "codexUsage.reviewProjectTransitions",
  "title": "Codex Usage: Review Project Transitions"
}
```

Add setting:

```json
"codexUsage.projectTransitions.autoDetect": {
  "type": "boolean",
  "default": true,
  "description": "Automatically split usage when high-confidence local repository transitions are detected."
}
```

- [ ] **Step 5: Add extension command**

In `extensions/vscode/src/extension.ts`, import `buildTransitionSuggestArgs` and `parseTransitionChoices`.

Register command in `activate()`:

```typescript
  const reviewProjectTransitionsCommand = vscode.commands.registerCommand("codexUsage.reviewProjectTransitions", async () => {
    await reviewProjectTransitions(context);
  });
```

Add it to `context.subscriptions.push(...)`.

Add function:

```typescript
async function reviewProjectTransitions(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings();
  try {
    const executablePath = await resolveBundledExecutable(context);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Detecting Codex project transitions",
      },
      () => runCodexUsage(executablePath, buildTransitionSuggestArgs({ sessionsDir: settings.sessionsDir }), buildCodexUsageEnv(settings.projectAliases)),
    );
    const choices = parseTransitionChoices(result.stdout);
    if (choices.length === 0) {
      void vscode.window.showInformationMessage("No high-confidence Codex project transitions were found.");
      return;
    }
    const selected = await vscode.window.showQuickPick(choices, {
      canPickMany: true,
      placeHolder: "Review detected project transitions",
    });
    if (!selected) {
      return;
    }
    const message =
      selected.length === 0
        ? "No project transitions selected. Automatic high-confidence transitions still apply in reports."
        : `${selected.length} project transition${selected.length === 1 ? "" : "s"} selected for review. Automatic high-confidence transitions apply in reports.`;
    void vscode.window.showInformationMessage(message);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to review project transitions: ${message}`);
  }
}
```

This command is review-only in this slice because high-confidence transitions apply automatically. Manual accept/deny persistence can be added later as an override layer.

- [ ] **Step 6: Run TypeScript tests to verify Task 9 passes**

Run:

```powershell
cd extensions/vscode
npm test
```

Expected: tests pass.

- [ ] **Step 7: Commit Task 9**

Run:

```powershell
git add extensions/vscode/src/core.ts extensions/vscode/src/extension.ts extensions/vscode/package.json extensions/vscode/package-lock.json extensions/vscode/test/core.test.js
git commit -m "feat: add project transition review command"
```

Expected: commit succeeds.

---

### Task 10: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update root README**

In `README.md`, add under `Accounting And Pricing`:

```markdown
## Project Transitions

Codex Usage can automatically split usage when a thread clearly moves from one local Git repository to another. Detection requires high-confidence local evidence: a timestamped Codex event must reference an existing local path, and that path must resolve to a Git remote through `.git/config`.

For example, if older structured metadata says `signoz-stack` but a later event references `D:\...\ops-board`, and that folder resolves to `https://github.com/Wenjun-Mao/ops-board.git`, usage before the detected timestamp stays under `signoz-stack` and later usage is reported under `ops-board`.

The tool does not split usage from casual name mentions alone. Reports include detected transition metadata so the split is visible and auditable.
```

- [ ] **Step 2: Update extension README**

In `extensions/vscode/README.md`, add to features:

```markdown
- Automatically splits usage across verified repository transitions and shows the transition in the report.
```

Add to commands:

```markdown
- `Codex Usage: Review Project Transitions`
```

Add to settings:

```markdown
- `codexUsage.projectTransitions.autoDetect`: automatically split high-confidence repository transitions.
```

- [ ] **Step 3: Update changelog**

In `CHANGELOG.md`, add under the unreleased or latest beta section:

```markdown
- Added automatic high-confidence project transition detection for repo rename/move cases.
- Added `Codex Usage: Review Project Transitions`.
- Reports now show detected project transitions and split usage at the verified switch timestamp.
```

- [ ] **Step 4: Run full Python tests**

Run:

```powershell
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 5: Run full TypeScript tests**

Run:

```powershell
cd extensions/vscode
npm test
```

Expected: all tests pass.

- [ ] **Step 6: Real local smoke for current `ops-board` case**

Run from repo root:

```powershell
uv run codex-usage summary --range today --by project --json
uv run codex-usage transitions suggest --json
uv run codex-usage report --range today --output output\project-transitions-smoke.html
```

Expected:

- `summary` shows `signoz-stack` and `ops-board` as separate project rows when the verified switch point exists.
- `transitions suggest` includes `signoz-stack -> ops-board`.
- HTML report contains `Project Transitions`.

- [ ] **Step 7: Rebuild bundled executable and VSIX**

Run:

```powershell
cd extensions/vscode
npm run package:vsix:win
```

Expected:

- `extensions/vscode/bin/win32-x64/codex-usage.exe` is rebuilt.
- `output/codex-usage-dashboard-win32-x64.vsix` is rebuilt.
- `vsce` includes `extension/bin/win32-x64/codex-usage.exe`, `extension/out/*.js`, and `extension/package.json`.

- [ ] **Step 8: Bundled executable smoke**

Run from repo root:

```powershell
extensions\vscode\bin\win32-x64\codex-usage.exe transitions suggest --json
extensions\vscode\bin\win32-x64\codex-usage.exe report --range today --output output\project-transitions-bundled-smoke.html
```

Expected:

- `transitions suggest` exits `0` and prints JSON.
- Bundled report exits `0` and writes the HTML file.

- [ ] **Step 9: Commit documentation and verification updates**

Run:

```powershell
git add README.md extensions/vscode/README.md CHANGELOG.md
git commit -m "docs: document project transitions"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: The plan covers automatic detection, verified path plus Git-origin evidence, timestamped splitting, connected report metadata, CLI review, VS Code review, opt-out behavior, tests, docs, and VSIX rebuild.
- Placeholder scan: No unfinished-marker or vague "add tests" steps remain. Each test and implementation task includes concrete code or commands.
- Scope check: This is a single implementation slice. It intentionally does not add manual transition override persistence, conflict editing, or network GitHub rename detection.
- Type consistency: The plan consistently uses `ProjectTransition`, `RepoPathObservation`, `collect_repo_path_observations`, `infer_project_transitions`, and `apply_project_transitions`.
- Risk note: `state_5.sqlite` timestamps may be thread-level rather than event-level. JSONL event timestamps should win when both sources exist; SQLite evidence is still useful for review and for threads whose first prompt contains the verified repo path.
