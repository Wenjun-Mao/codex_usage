"""Recognize explicit history semantics without upgrading a resume artifact."""


def history_contract_sql(alias="p"):
    if alias not in {"p", "parser_checkpoints"}:
        raise ValueError("unsupported checkpoint alias")
    state = f"{alias}.state_json"
    return f"""case when json_valid({state}) then
        json_type({state}, '$')='object'
        and json_type({state}, '$.history_baseline_pending') in ('true','false')
        and json_type({state}, '$.history_boundary_digest')='text'
        and json_type({state}, '$.root_inline_replay_possible') in ('true','false')
        and (json_type({state}, '$.root_metadata')='null' or (
            json_type({state}, '$.root_metadata')='object'
            and json_type({state}, '$.root_metadata.history_mode')='text'
            and json_type({state}, '$.root_metadata.history_base') in ('null','object')
            and json_type({state}, '$.root_metadata.history_ordinal') in ('null','integer')
            and json_type({state}, '$.root_metadata.forked_from_ordinal_exclusive') in ('null','integer')
        )) else 0 end"""


def supports_history_resume(connection, source_key):
    row = connection.execute(f"select coalesce(({history_contract_sql()}),0) from parser_checkpoints p where file_key=?",
                             (source_key,)).fetchone()
    return row is not None and bool(row[0])
