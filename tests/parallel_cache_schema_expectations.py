from __future__ import annotations

type SchemaObject = tuple[str, str, str, str]

EXPECTED_SCHEMA_META = (
    ("parser_version", "6"),
    ("project_transition_version", "2"),
    ("project_transitions_dirty", "1"),
    ("schema_version", "8"),
    ("storage_metadata_version", "2"),
)
EXPECTED_SQLITE_MASTER: tuple[SchemaObject, ...] = (
    (
        "index",
        "sqlite_autoindex_dirty_transition_tasks_1",
        "dirty_transition_tasks",
        "",
    ),
    ("index", "sqlite_autoindex_files_1", "files", ""),
    ("index", "sqlite_autoindex_parser_checkpoints_1", "parser_checkpoints", ""),
    ("index", "sqlite_autoindex_schema_meta_1", "schema_meta", ""),
    ("index", "sqlite_autoindex_session_metadata_1", "session_metadata", ""),
    (
        "index",
        "sqlite_autoindex_storage_content_diagnostics_1",
        "storage_content_diagnostics",
        "",
    ),
    ("index", "sqlite_autoindex_storage_files_1", "storage_files", ""),
    ("index", "sqlite_autoindex_transition_candidates_1", "transition_candidates", ""),
    ("index", "sqlite_autoindex_usage_records_1", "usage_records", ""),
    (
        "index",
        "storage_content_diagnostics_task_idx",
        "storage_content_diagnostics",
        "CREATE INDEX storage_content_diagnostics_task_idx on storage_content_diagnostics (task_id)",
    ),
    (
        "index",
        "storage_files_project_idx",
        "storage_files",
        "CREATE INDEX storage_files_project_idx on storage_files (project_key)",
    ),
    (
        "index",
        "storage_files_task_idx",
        "storage_files",
        "CREATE INDEX storage_files_task_idx on storage_files (task_id)",
    ),
    (
        "index",
        "transition_candidates_thread_idx",
        "transition_candidates",
        "CREATE INDEX transition_candidates_thread_idx on transition_candidates (thread_id)",
    ),
    (
        "index",
        "usage_records_session_timestamp_idx",
        "usage_records",
        "CREATE INDEX usage_records_session_timestamp_idx on usage_records (session_id, timestamp_us)",
    ),
    (
        "index",
        "usage_records_timestamp_us_idx",
        "usage_records",
        "CREATE INDEX usage_records_timestamp_us_idx on usage_records (timestamp_us)",
    ),
    (
        "table",
        "dirty_transition_tasks",
        "dirty_transition_tasks",
        "CREATE TABLE dirty_transition_tasks ( thread_id text primary key )",
    ),
    (
        "table",
        "files",
        "files",
        "CREATE TABLE files ( file_key text primary key, path text not null, "  # noqa: ISC004
        "session_dir text not null, storage_state text not null, size_bytes integer not null, mtime_ns integer not null, "
        "parsed_at text not null, last_seen_at text not null, missing_since text, is_missing integer not null, session_id text, error text )",
    ),
    (
        "table",
        "parser_checkpoints",
        "parser_checkpoints",
        "CREATE TABLE parser_checkpoints ( file_key text primary key, "  # noqa: ISC004
        "byte_offset integer not null, next_record_index integer not null, next_candidate_index integer not null, "
        "source_device text not null, source_inode text not null, head_sha256 text not null, boundary_sha256 text not null, "
        "session_id text not null, state_json text not null )",
    ),
    (
        "table",
        "project_transitions",
        "project_transitions",
        "CREATE TABLE project_transitions ( owner_thread_id text not null, source_key text not null, "  # noqa: ISC004
        "source_label text not null, target_key text not null, target_label text not null, effective_from text not null, "
        "confidence integer not null, evidence_json text not null, thread_ids_json text not null )",
    ),
    (
        "table",
        "schema_meta",
        "schema_meta",
        "CREATE TABLE schema_meta (key text primary key, value text not null)",
    ),
    (
        "table",
        "session_metadata",
        "session_metadata",
        "CREATE TABLE session_metadata ( file_key text primary key, "  # noqa: ISC004
        "file_path text not null, session_dir text not null, storage_state text not null, is_missing integer not null, "
        "session_id text not null, cwd text, project_key text, project_label text, project_aliases_json text not null, "
        "git_repository_url text, git_branch text, memory_mode text, has_base_instructions integer not null, session_bytes integer not null, estimated_sync_bytes integer not null )",
    ),
    (
        "table",
        "storage_content_diagnostics",
        "storage_content_diagnostics",
        "CREATE TABLE storage_content_diagnostics ( path text primary key, "  # noqa: ISC004
        "task_id text not null, analyzed_offset integer not null check (analyzed_offset >= 0), "
        "source_device text not null, source_inode text not null, source_mtime_ns integer not null, "
        "head_sha256 text not null, boundary_sha256 text not null, "
        "compacted_record_count integer not null check (compacted_record_count >= 0), "
        "compacted_bytes integer not null check (compacted_bytes >= 0), "
        "largest_compacted_record_bytes integer not null check (largest_compacted_record_bytes >= 0), "
        "media_compacted_record_count integer not null check (media_compacted_record_count >= 0), "
        "embedded_media_occurrence_count integer not null check (embedded_media_occurrence_count >= 0), "
        "unclassified_record_count integer not null check (unclassified_record_count >= 0), "
        "last_analyzed_at text not null, error text not null )",
    ),
    (
        "table",
        "storage_files",
        "storage_files",
        "CREATE TABLE storage_files ( path text primary key, "  # noqa: ISC004
        "session_dir text not null, storage_state text not null, size_bytes integer not null check (size_bytes >= 0), "
        "mtime_ns integer not null, last_seen_at text not null, is_missing integer not null check (is_missing in (0, 1)), "
        "task_id text not null, parent_task_id text not null, usage_role text not null check (usage_role in ('root', 'subagent')), "
        "project_key text not null, project_label text not null, project_aliases_json text not null, task_title text not null, "
        "title_index_path text not null, title_index_size integer not null, title_index_mtime_ns integer not null, metadata_diagnostic text not null )",
    ),
    (
        "table",
        "transition_candidates",
        "transition_candidates",
        "CREATE TABLE transition_candidates ( file_key text not null, "  # noqa: ISC004
        "candidate_index integer not null, timestamp text not null, timestamp_us integer not null, thread_id text not null, "
        "raw_path text not null, source text not null, primary key (file_key, candidate_index) )",
    ),
    (
        "table",
        "usage_records",
        "usage_records",
        "CREATE TABLE usage_records ( file_key text not null, file_path text not null, "  # noqa: ISC004
        "record_index integer not null, timestamp text not null, timestamp_us integer not null, session_id text not null, "
        "turn_id text, model text not null, effort text, collaboration_mode text, project_key text not null, "
        "project_label text not null, project_aliases_json text not null, cwd text, git_repository_url text, "
        "git_branch text, parent_thread_id text, usage_role text not null check (usage_role in ('root', 'subagent')), input_tokens integer not null, cached_input_tokens integer not null, "
        "cache_write_input_tokens integer not null default 0, output_tokens integer not null, reasoning_output_tokens integer not null, total_tokens integer not null, "
        "primary key (file_key, record_index) )",
    ),
)
