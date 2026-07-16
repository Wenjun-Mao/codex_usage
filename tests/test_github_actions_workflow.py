import ast
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "package-vsix.yml"
PACKAGED_SYNC_SMOKE = ROOT / "scripts" / "smoke-test-packaged-sync.py"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
EXTENSION_ROOT = ROOT / "extensions" / "vscode"
EXTENSION_PACKAGE = EXTENSION_ROOT / "package.json"
EXTENSION_PACKAGE_LOCK = EXTENSION_ROOT / "package-lock.json"
CHANGELOGS = (ROOT / "CHANGELOG.md", EXTENSION_ROOT / "CHANGELOG.md")
NATIVE_BUILD_SCRIPTS = (
    ROOT / "scripts" / "build-macos-arm64-exe.sh",
    ROOT / "scripts" / "build-windows-exe.ps1",
)


def read_workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def extract_workflow_job(text: str, job_name: str) -> str:
    jobs = text.split("\njobs:\n", 1)[1]
    headers = list(
        re.finditer(r"^  (?P<name>[A-Za-z0-9_-]+):\n", jobs, re.MULTILINE)
    )
    for index, header in enumerate(headers):
        if header.group("name") != job_name:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(jobs)
        return jobs[header.end() : end]
    raise AssertionError(f"Workflow job not found: {job_name}")


def load_packaged_sync_smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "packaged_sync_smoke",
        PACKAGED_SYNC_SMOKE,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load smoke module from {PACKAGED_SYNC_SMOKE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def markdown_section(path: Path, heading: str) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(f"{heading}\n")
    level = heading.split(maxsplit=1)[0]
    end_match = re.search(rf"^{re.escape(level)} (?!#)", text[start + len(heading) + 1 :], re.MULTILINE)
    end = len(text) if end_match is None else start + len(heading) + 1 + end_match.start()
    return text[start:end]


def inventory_payload(
    availability: str,
    *,
    thread_id: str = "thread-1",
    estimated_sync_bytes: int = 498,
    candidate_roots: list[str] | None = None,
) -> dict[str, object]:
    states = {
        "local": ("local_only", "push"),
        "remote": ("remote_only", "pull"),
        "both": ("synced", "none"),
    }
    state, action = states[availability]
    return {
        "inventory_version": 2,
        "projects": [
            {
                "project_key": "https://github.com/example/packaged-sync-smoke",
                "project_label": "packaged-sync-smoke",
                "identity_kind": "git",
                "candidate_roots": candidate_roots or [],
                "tasks": [
                    {
                        "thread_id": thread_id,
                        "title": "Packaged sync smoke",
                        "updated_at": "2026-04-29T10:00:02Z",
                        "estimated_sync_bytes": estimated_sync_bytes,
                        "availability": availability,
                        "state": state,
                        "action": action,
                    }
                ],
            }
        ],
        "issues": [],
    }


def sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def sync_result(direction: str) -> dict[str, object]:
    pushed = direction == "push"
    return {
        "outcome": "completed",
        "counts": {
            "discovered": 1 if pushed else 0,
            "selected": 1,
            "remote": 0 if pushed else 1,
            "pulled": 0 if pushed else 1,
            "pushed": 1 if pushed else 0,
            "unchanged": 0,
            "conflicts": 0,
            "issues": 0,
        },
        "pulled": [] if pushed else ["thread-1"],
        "pushed": ["thread-1"] if pushed else [],
        "issues": [],
    }


def test_workflow_has_manual_and_tag_triggers():
    text = read_workflow()

    assert "workflow_dispatch:" in text
    assert "publish:" in text
    assert "type: boolean" in text
    assert "default: false" in text
    assert "push:" in text
    assert '"v*"' in text


def test_workflow_names_platform_vsix_files():
    text = read_workflow()

    assert "codex-usage-dashboard-win32-x64.vsix" in text
    assert "codex-usage-dashboard-darwin-arm64.vsix" in text


@pytest.mark.parametrize(
    ("job_name", "runner", "package_command"),
    (
        ("windows", "windows-2025", "npm run package:vsix:win"),
        ("macos", "macos-26", "npm run package:vsix:mac"),
    ),
)
def test_native_workflow_jobs_test_before_packaging(
    job_name: str,
    runner: str,
    package_command: str,
):
    job = extract_workflow_job(read_workflow(), job_name)

    assert f"runs-on: {runner}" in job
    assert f"run: {package_command}" in job
    assert job.index("run: uv run pytest -q") < job.index("run: npm test")
    assert job.index("run: npm test") < job.index(f"run: {package_command}")


@pytest.mark.parametrize("build_script", NATIVE_BUILD_SCRIPTS, ids=lambda path: path.name)
def test_native_build_scripts_run_packaged_sync_smoke(build_script: Path):
    text = build_script.read_text(encoding="utf-8")

    assert "smoke-test-packaged-sync.py" in text


def test_packaged_transfer_smoke_uses_v3_without_desktop_project_state() -> None:
    source = PACKAGED_SYNC_SMOKE.read_text(encoding="utf-8")

    assert "INVENTORY_VERSION = 2" in source
    assert "SYNC_FORMAT_VERSION = 3" in source
    assert 'TASKS_DIRNAME = "tasks"' in source
    assert '"--candidate-project-root"' in source
    assert ".codex-global-state.json" not in source
    assert 'sync_dir / "conversations"' not in source


def test_release_workflow_keeps_only_supported_platform_targets() -> None:
    workflow = read_workflow()

    assert "win32-x64" in workflow
    assert "darwin-arm64" in workflow
    assert "linux-x64" not in workflow


def test_packaged_sync_smoke_orchestrates_isolated_exact_task_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    smoke = load_packaged_sync_smoke()
    executable = tmp_path / "codex-usage-double"
    executable.write_text("controlled executable double\n", encoding="utf-8")
    calls: list[tuple[Path, tuple[str, ...], dict[str, str]]] = []

    def write_baseline(
        codex_home: Path,
        local_bytes: bytes,
        remote_bytes: bytes,
    ) -> None:
        baseline = (
            codex_home
            / ".codex-sync-state"
            / "fingerprint"
            / "threads"
            / f"{smoke.THREAD_ID}.json"
        )
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(
                {
                    "sync_version": 2,
                    "thread_id": smoke.THREAD_ID,
                    "sync_dir_fingerprint": "fingerprint",
                    "base_sha256": sha256_bytes(local_bytes),
                    "base_size_bytes": len(local_bytes),
                    "base_updated_at": smoke.TASK_UPDATED_AT,
                    "last_remote_sha256": sha256_bytes(remote_bytes),
                    "last_local_sha256": sha256_bytes(local_bytes),
                    "source_relative_path": smoke.SESSION_RELATIVE_PATH.as_posix(),
                    "project_key": smoke.PROJECT_KEY,
                    "project_label": smoke.PROJECT_LABEL,
                    "synced_at": "2026-07-16T12:00:00Z",
                }
            ),
            encoding="utf-8",
        )

    def run_double(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        codex_home = Path(environment["CODEX_HOME"])
        command_args = tuple(command[1:])
        calls.append((codex_home, command_args, environment))
        sync_dir = Path(command_args[3])
        source_home = calls[0][0]
        source_jsonl = source_home / "sessions" / smoke.SESSION_RELATIVE_PATH

        if len(calls) == 1:
            payload = inventory_payload(
                "local",
                estimated_sync_bytes=source_jsonl.stat().st_size + 4096,
            )
        elif len(calls) == 2:
            source_bytes = source_jsonl.read_bytes()
            remote_jsonl = sync_dir / "tasks" / f"{smoke.THREAD_ID}.jsonl"
            remote_jsonl.parent.mkdir(parents=True, exist_ok=True)
            remote_jsonl.write_bytes(source_bytes)
            (sync_dir / "sync-index.json").write_text(
                json.dumps(
                    {
                        "format_version": 3,
                        "updated_at": "2026-07-16T12:00:00Z",
                        "threads": {
                            smoke.THREAD_ID: {
                                "file": f"tasks/{smoke.THREAD_ID}.jsonl",
                                "source_relative_path": smoke.SESSION_RELATIVE_PATH.as_posix(),
                                "index_entry": {
                                    "id": smoke.THREAD_ID,
                                    "thread_name": smoke.TASK_TITLE,
                                    "updated_at": smoke.TASK_UPDATED_AT,
                                },
                                "project_key": smoke.PROJECT_KEY,
                                "project_label": smoke.PROJECT_LABEL,
                                "project_aliases": [],
                                "sha256": sha256_bytes(source_bytes),
                                "size_bytes": len(source_bytes),
                                "session_updated_at": smoke.TASK_UPDATED_AT,
                                "exported_at": "2026-07-16T12:00:00Z",
                                "source_machine_id": "packaged-smoke",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            write_baseline(source_home, source_bytes, source_bytes)
            payload = sync_result("push")
        elif len(calls) == 3:
            candidate_index = command_args.index("--candidate-project-root")
            candidate_root = command_args[candidate_index + 1]
            payload = inventory_payload(
                "remote",
                estimated_sync_bytes=source_jsonl.stat().st_size,
                candidate_roots=[candidate_root],
            )
        elif len(calls) == 4:
            candidate_index = command_args.index("--candidate-project-root")
            candidate_root = command_args[candidate_index + 1]
            remote_jsonl = sync_dir / "tasks" / f"{smoke.THREAD_ID}.jsonl"
            imported_jsonl = codex_home / "sessions" / smoke.SESSION_RELATIVE_PATH
            rows = [
                json.loads(line)
                for line in remote_jsonl.read_text(encoding="utf-8").splitlines()
            ]
            rows[0]["payload"]["cwd"] = candidate_root
            smoke._write_jsonl(imported_jsonl, rows)
            write_baseline(codex_home, imported_jsonl.read_bytes(), remote_jsonl.read_bytes())
            payload = sync_result("pull")
        elif len(calls) == 5:
            candidate_index = command_args.index("--candidate-project-root")
            candidate_root = command_args[candidate_index + 1]
            imported_jsonl = codex_home / "sessions" / smoke.SESSION_RELATIVE_PATH
            remote_jsonl = sync_dir / "tasks" / f"{smoke.THREAD_ID}.jsonl"
            imported_meta = json.loads(
                imported_jsonl.read_text(encoding="utf-8").splitlines()[0]
            )
            payload = {
                "threads": [
                    {
                        "thread_id": smoke.THREAD_ID,
                        "state": "synced",
                        "action": "none",
                        "reason": "local and remote match their last synchronized versions",
                        "local_path": str(imported_jsonl),
                        "remote_path": str(remote_jsonl),
                        "local_sha256": sha256_bytes(imported_jsonl.read_bytes()),
                        "remote_sha256": sha256_bytes(remote_jsonl.read_bytes()),
                        "base_sha256": sha256_bytes(imported_jsonl.read_bytes()),
                        "updated_at": smoke.TASK_UPDATED_AT,
                        "source_relative_path": smoke.SESSION_RELATIVE_PATH.as_posix(),
                        "project_key": smoke.PROJECT_KEY,
                        "project_label": smoke.PROJECT_LABEL,
                        "memory_database_rows": 0,
                    }
                ],
                "issues": [],
            }
            assert candidate_root == imported_meta["payload"]["cwd"]
        else:
            raise AssertionError(f"Unexpected packaged command: {command!r}")
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(smoke, "subprocess", SimpleNamespace(run=run_double))
    monkeypatch.setattr(
        sys,
        "argv",
        [str(PACKAGED_SYNC_SMOKE), "--executable", str(executable)],
    )

    assert smoke.main() == 0

    source_home = calls[0][0]
    target_home = calls[2][0]
    sync_dir = calls[0][1][3]
    candidate_root = calls[2][1][-1]
    assert source_home.name == "source-home"
    assert target_home.name == "target-home"
    assert source_home != target_home
    assert [call[0] for call in calls] == [
        source_home,
        source_home,
        target_home,
        target_home,
        target_home,
    ]
    assert [call[1] for call in calls] == [
        ("sync", "inventory", "--sync-dir", sync_dir, "--json"),
        (
            "sync",
            "push",
            "--sync-dir",
            sync_dir,
            "--thread-id",
            smoke.THREAD_ID,
            "--json",
        ),
        (
            "sync",
            "inventory",
            "--sync-dir",
            sync_dir,
            "--json",
            "--candidate-project-root",
            candidate_root,
        ),
        (
            "sync",
            "pull",
            "--sync-dir",
            sync_dir,
            "--thread-id",
            smoke.THREAD_ID,
            "--json",
            "--candidate-project-root",
            candidate_root,
        ),
        (
            "sync",
            "status",
            "--sync-dir",
            sync_dir,
            "--thread-id",
            smoke.THREAD_ID,
            "--json",
            "--candidate-project-root",
            candidate_root,
        ),
    ]
    assert not (target_home / ".codex-global-state.json").exists()
    assert sum(call[1][1] == "push" for call in calls) == 1
    assert sum(call[1][1] == "pull" for call in calls) == 1
    assert capsys.readouterr().out.strip() == (
        "Packaged sync smoke passed: "
        "inventory=local,remote pushed=1 pulled=1 status=up-to-date format_version=3"
    )


@pytest.mark.parametrize(
    ("payload", "availability", "message"),
    (
        ({**inventory_payload("local"), "inventory_version": 1}, "local", "inventory_version"),
        ({**inventory_payload("local"), "issues": [{"code": "issue"}]}, "local", "issues"),
        (inventory_payload("local", thread_id="wrong-thread"), "local", "thread id"),
        (inventory_payload("both"), "local", "availability"),
    ),
)
def test_packaged_sync_inventory_validation_rejects_contract_mismatches(
    payload: dict[str, object],
    availability: str,
    message: str,
):
    smoke = load_packaged_sync_smoke()

    with pytest.raises(RuntimeError, match=message):
        smoke._validate_inventory(payload, availability, 498)


@pytest.mark.parametrize(
    ("payload", "direction", "message"),
    (
        ({**sync_result("push"), "pushed": ["wrong-thread"]}, "push", "pushed thread ids"),
        (
            {
                **sync_result("push"),
                "counts": {**sync_result("push")["counts"], "pushed": 2},
            },
            "push",
            "counts",
        ),
        ({**sync_result("pull"), "pulled": ["wrong-thread"]}, "pull", "pulled thread ids"),
    ),
)
def test_packaged_sync_result_validation_rejects_identity_and_count_mismatches(
    payload: dict[str, object],
    direction: str,
    message: str,
):
    smoke = load_packaged_sync_smoke()

    with pytest.raises(RuntimeError, match=message):
        smoke._validate_sync_result(payload, direction)


@pytest.mark.parametrize(
    ("completed", "message"),
    (
        (subprocess.CompletedProcess([], 7, "stdout", "stderr"), "exited with code 7"),
        (subprocess.CompletedProcess([], 0, "not-json", ""), "not one JSON object"),
        (subprocess.CompletedProcess([], 0, "[]", ""), "non-object JSON"),
    ),
)
def test_packaged_json_runner_rejects_command_and_payload_errors(
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[str],
    message: str,
):
    smoke = load_packaged_sync_smoke()
    monkeypatch.setattr(
        smoke,
        "subprocess",
        SimpleNamespace(run=lambda *args, **kwargs: completed),
    )

    with pytest.raises(RuntimeError, match=message):
        smoke._run_json(Path("codex-usage"), Path("codex-home"), ["sync", "inventory"])


def test_packaged_sync_smoke_has_no_optimization_sensitive_asserts():
    tree = ast.parse(PACKAGED_SYNC_SMOKE.read_text(encoding="utf-8"))

    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]


def test_release_metadata_versions_are_0_1_36():
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    uv_lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    extension_package = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    extension_lock = json.loads(EXTENSION_PACKAGE_LOCK.read_text(encoding="utf-8"))

    codex_usage_lock = next(
        package for package in uv_lock["package"] if package["name"] == "codex-usage"
    )
    assert pyproject["project"]["version"] == "0.1.36"
    assert codex_usage_lock["version"] == "0.1.36"
    assert extension_package["version"] == "0.1.36"
    assert extension_lock["version"] == "0.1.36"
    assert extension_lock["packages"][""]["version"] == "0.1.36"


@pytest.mark.parametrize(
    "readme",
    (
        ROOT / "README.md",
        EXTENSION_ROOT / "README.md",
    ),
    ids=("repository", "extension"),
)
def test_task_transfer_documentation_describes_current_release_contract(readme: Path):
    transfer = markdown_section(readme, "## Task Transfer").casefold()

    assert "import tasks" in transfer and "export tasks" in transfer
    assert "fresh, empty selection" in transfer
    assert "desktop app is not required" in transfer
    assert "open vs code workspace folders" in transfer
    assert "validated local folder" in transfer
    assert "tasks/" in transfer and ("version 3" in transfer or "version-3" in transfer)
    assert "selected batch" in transfer
    assert "complete operation" in transfer or "whole operation" in transfer
    assert "task selections" in transfer and "project mappings" in transfer
    assert "not saved" in transfer or "neither" in transfer


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_0_1_34_changelog_describes_complete_release_contract(changelog: Path):
    section = markdown_section(
        changelog,
        "## 0.1.34 - 2026-07-14 - Exact Task Sync Selection",
    ).casefold()

    assert "project-grouped task picker" in section and "exact selected task thread ids" in section
    assert "tasks currently shown" in section
    assert "future tasks" in section and "explicitly selected" in section
    assert "remote-only task discovery" in section
    assert "selection schema" in section and "project/conversation" in section
    assert "setup required" in section and "does not migrate" in section
    assert "version-2 remote layout" in section
    assert "no remote cleanup or republish" in section
    assert "version-1" in section and "clean resync" in section
    assert "user-facing" in section and "technical" in section and "thread id" in section
    assert "macos apple silicon packaged inventory/push/pull verified locally" in section
    assert "windows x64 is a ci-only release gate" in section
    assert "full-jsonl" in section and "built-in codex handoff" in section


def test_workflow_uploads_artifacts_before_publishing():
    text = read_workflow()

    assert "actions/upload-artifact@v6" in text
    assert "actions/download-artifact@v6" in text
    assert "if-no-files-found: error" in text
    assert "retention-days: 14" in text


def test_publish_job_requires_secret_and_release_guard():
    text = read_workflow()

    assert "VSCE_PAT: ${{ secrets.VSCE_PAT }}" in text
    assert "    env:\n      VSCE_PAT: ${{ secrets.VSCE_PAT }}" not in text
    assert "npx vsce publish --skip-duplicate --packagePath" in text
    assert "startsWith(github.ref, 'refs/tags/v')" in text
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "inputs.publish" in text


def test_publish_job_has_release_preflight_and_rerunnable_publish():
    text = read_workflow()

    assert "fetch-depth: 0" in text
    assert "Verify release tag" in text
    assert "GITHUB_REF_NAME" in text
    assert "expected_tag=\"v${version}\"" in text
    assert "git merge-base --is-ancestor" in text
    assert "--skip-duplicate" in text
    assert text.count("npx vsce publish") == 1
