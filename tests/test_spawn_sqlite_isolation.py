from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path

from parallel_cache_test_support import write_usage_corpus
from parallel_transition_test_support import write_transition_corpus
from spawn_worker_test_support import guarded_transition_worker, guarded_usage_worker

from codex_usage.parallel.execution import OrderedProcessMapper
from codex_usage.parallel.transitions import TransitionScanRequest
from codex_usage.parallel.usage import UsageParseRequest

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


def module_path(module_name: str) -> Path | None:
    relative = Path(*module_name.split("."))
    module_file = (SOURCE_ROOT / relative).with_suffix(".py")
    package_file = SOURCE_ROOT / relative / "__init__.py"
    if module_file.is_file():
        return module_file
    if package_file.is_file():
        return package_file
    return None


def local_import_closure(
    entry_modules: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    pending = list(entry_modules)
    visited: dict[str, tuple[str, ...]] = {}
    while pending:
        module_name = pending.pop()
        if module_name in visited:
            continue
        path = module_path(module_name)
        assert path is not None, module_name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: set[str] = set()
        package = (
            module_name
            if path.name == "__init__.py"
            else module_name.rpartition(".")[0]
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                dynamic_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else f"{getattr(node.func.value, 'id', '')}.{node.func.attr}"
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                assert dynamic_name not in {
                    "__import__",
                    "importlib.import_module",
                }, path
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    target = importlib.util.resolve_name(
                        "." * node.level + (node.module or ""), package
                    )
                else:
                    target = node.module or ""
                imports.add(target)
                for alias in node.names:
                    candidate = f"{target}.{alias.name}" if target else alias.name
                    if module_path(candidate) is not None:
                        imports.add(candidate)
        visited[module_name] = tuple(sorted(imports))
        pending.extend(
            name
            for name in imports
            if name.startswith("codex_usage.") and module_path(name) is not None
        )
    return visited


def test_spawned_usage_and_transition_workers_cannot_open_sqlite(
    tmp_path: Path,
) -> None:
    usage_corpus = write_usage_corpus(tmp_path / "usage")
    usage_requests = []
    for ordinal, path in enumerate(usage_corpus.ordered_paths[:2]):
        stat = path.stat()
        usage_requests.append(
            UsageParseRequest(
                ordinal, path.stem, path, stat.st_size, stat.st_mtime_ns
            )
        )
    transition_corpus = write_transition_corpus(tmp_path / "transition")
    transition_requests = [
        TransitionScanRequest(ordinal, path)
        for ordinal, path in enumerate(transition_corpus.session_files)
    ]

    with OrderedProcessMapper(
        guarded_usage_worker, task_count=2, max_workers=2
    ) as usage_mapper:
        usage_results = usage_mapper.map_batch(usage_requests)
    with OrderedProcessMapper(
        guarded_transition_worker, task_count=2, max_workers=2
    ) as transition_mapper:
        transition_results = transition_mapper.map_batch(transition_requests)

    parent_pid = os.getpid()
    usage_pids = {result.span.pid for result in usage_results}
    transition_pids = {result.span.pid for result in transition_results}
    assert usage_mapper.worker_count == 2
    assert transition_mapper.worker_count == 2
    assert usage_pids and parent_pid not in usage_pids
    assert transition_pids and parent_pid not in transition_pids
    assert all(
        result.span.pid != parent_pid and result.error == ""
        for result in usage_results
    )
    assert all(result.generation and result.generation.records for result in usage_results)
    assert all(
        result.span.pid != parent_pid and result.error == ""
        for result in transition_results
    )
    assert all(result.candidates for result in transition_results)
    assert usage_mapper.used_serial_fallback is False
    assert transition_mapper.used_serial_fallback is False


def test_worker_import_closure_has_no_sqlite_or_parent_store_dependency() -> None:
    closure = local_import_closure(
        (
            "codex_usage.parallel.usage",
            "codex_usage.session_generation_models",
            "codex_usage.parallel.transitions",
            "codex_usage.project_transition_candidates",
        )
    )
    forbidden = {
        "sqlite3",
        "codex_usage.project_transition_state",
        "codex_usage.project_transition_collection",
        "codex_usage.session_cache",
        "codex_usage.session_cache_schema",
        "codex_usage.session_cache_store",
        "codex_usage.session_cache_refresh",
    }
    imported = {name for names in closure.values() for name in names}
    assert imported.isdisjoint(forbidden)
    assert "codex_usage.project_transition_state" not in closure
    collection_imports = local_import_closure(
        ("codex_usage.project_transition_collection",)
    )["codex_usage.project_transition_collection"]
    assert "codex_usage.project_transition_state" in collection_imports
