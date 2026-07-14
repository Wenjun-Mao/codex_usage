import ast
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
) -> dict[str, object]:
    return {
        "inventory_version": 1,
        "projects": [
            {
                "project_key": "/tmp/packaged-sync-smoke",
                "project_label": "packaged-sync-smoke",
                "tasks": [
                    {
                        "thread_id": thread_id,
                        "title": "Packaged sync smoke",
                        "updated_at": "2026-04-29T10:00:02Z",
                        "estimated_sync_bytes": estimated_sync_bytes,
                        "availability": availability,
                    }
                ],
            }
        ],
        "issues": [],
    }


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


def test_packaged_sync_smoke_orchestrates_isolated_exact_task_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    smoke = load_packaged_sync_smoke()
    executable = tmp_path / "codex-usage-double"
    executable.write_text("controlled executable double\n", encoding="utf-8")
    calls: list[tuple[Path, tuple[str, ...], dict[str, str]]] = []

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
            remote_jsonl = sync_dir / "conversations" / f"{smoke.THREAD_ID}.jsonl"
            remote_jsonl.parent.mkdir(parents=True, exist_ok=True)
            remote_jsonl.write_bytes(source_jsonl.read_bytes())
            (sync_dir / "sync-index.json").write_text(
                json.dumps(
                    {
                        "format_version": 2,
                        "threads": {
                            smoke.THREAD_ID: {
                                "file": f"conversations/{smoke.THREAD_ID}.jsonl"
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            payload = sync_result("push")
        elif len(calls) == 3:
            payload = inventory_payload(
                "remote",
                estimated_sync_bytes=source_jsonl.stat().st_size,
            )
        elif len(calls) == 4:
            imported_jsonl = codex_home / "sessions" / smoke.SESSION_RELATIVE_PATH
            imported_jsonl.parent.mkdir(parents=True, exist_ok=True)
            imported_jsonl.write_bytes(
                (sync_dir / "conversations" / f"{smoke.THREAD_ID}.jsonl").read_bytes()
            )
            payload = sync_result("pull")
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
    assert source_home.name == "source-home"
    assert target_home.name == "target-home"
    assert source_home != target_home
    assert [call[0] for call in calls] == [
        source_home,
        source_home,
        target_home,
        target_home,
    ]
    assert [call[1] for call in calls] == [
        ("sync", "inventory", "--sync-dir", sync_dir, "--json"),
        (
            "sync",
            "run",
            "--sync-dir",
            sync_dir,
            "--thread-id",
            smoke.THREAD_ID,
            "--json",
        ),
        ("sync", "inventory", "--sync-dir", sync_dir, "--json"),
        (
            "sync",
            "run",
            "--sync-dir",
            sync_dir,
            "--thread-id",
            smoke.THREAD_ID,
            "--json",
        ),
    ]
    assert capsys.readouterr().out.strip() == (
        "Packaged sync smoke passed: "
        "inventory=local,remote pushed=1 pulled=1 format_version=2"
    )


@pytest.mark.parametrize(
    ("payload", "availability", "message"),
    (
        ({**inventory_payload("local"), "inventory_version": 2}, "local", "inventory_version"),
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


def test_release_metadata_versions_are_0_1_34():
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    uv_lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    extension_package = json.loads(EXTENSION_PACKAGE.read_text(encoding="utf-8"))
    extension_lock = json.loads(EXTENSION_PACKAGE_LOCK.read_text(encoding="utf-8"))

    codex_usage_lock = next(
        package for package in uv_lock["package"] if package["name"] == "codex-usage"
    )
    assert pyproject["project"]["version"] == "0.1.34"
    assert codex_usage_lock["version"] == "0.1.34"
    assert extension_package["version"] == "0.1.34"
    assert extension_lock["version"] == "0.1.34"
    assert extension_lock["packages"][""]["version"] == "0.1.34"


@pytest.mark.parametrize(
    ("readme", "sync_heading"),
    (
        (ROOT / "README.md", "## Experimental Task Sync"),
        (EXTENSION_ROOT / "README.md", "## Experimental Sync"),
    ),
    ids=("repository", "extension"),
)
def test_sync_documentation_describes_complete_breaking_release_contract(
    readme: Path,
    sync_heading: str,
):
    text = readme.read_text(encoding="utf-8")
    sync = markdown_section(readme, sync_heading).casefold()

    assert "one project-grouped `select tasks` picker" in sync
    assert "current-task shortcuts" in sync
    assert "remote-only tasks" in sync
    assert "future tasks" in sync and "explicitly selected" in sync
    assert "selection schema" in sync and "exact task" in sync
    assert "does not migrate" in sync and "project/conversation" in sync
    assert "**setup required**" in sync
    assert "version-2 remote layout" in sync
    assert "no remote cleanup or republish required" in sync
    assert "version-1" in sync and "clean resync" in sync
    assert "technical thread id" in sync
    assert "built-in codex handoff can fail" in sync and "full jsonl" in sync
    assert "macos apple silicon packaged inventory/push/pull verified locally" in text.casefold()
    assert "windows x64 packaging is ci-only" in text.casefold()
    assert "release gate" in text.casefold()


@pytest.mark.parametrize("changelog", CHANGELOGS, ids=("repository", "extension"))
def test_0_1_34_changelog_describes_complete_release_contract(changelog: Path):
    section = markdown_section(changelog, "## 0.1.34 - Exact Task Sync Selection").casefold()

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
