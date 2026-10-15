"""Destructive resets belong only to disposable parser caches, never ledgers."""
from codex_usage.ledger_writer_contract import assert_disposable_cache_reset


def drop_disposable_cache_schema(connection, indexes):
    assert_disposable_cache_reset(connection)
    for index in sorted(indexes):
        connection.execute(f"drop index if exists {index}")
    for table in (
        "speed_cache_facts", "speed_cache_tools", "speed_cache_uncertain_tools", "speed_cache_dirty",
        "quota_cache", "project_transitions", "dirty_transition_tasks", "transition_candidates",
        "image_operations", "parser_checkpoints", "storage_content_diagnostics", "storage_files",
        "session_metadata", "usage_records", "files", "schema_meta",
    ):
        connection.execute(f"drop table if exists {table}")
