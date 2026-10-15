"""Recognize explicit history semantics without upgrading a resume artifact."""


def history_contract_sql(alias="p"):
    if alias not in {"p", "parser_checkpoints"}:
        raise ValueError("unsupported checkpoint alias")
    state = f"{alias}.state_json"
    dependency = "(case when d.type='object' then d.value else '{}' end)"
    valid_dependencies = " and ".join([
        f"json_type({dependency},'$.thread_id')='text'",
        f"length(json_extract({dependency},'$.thread_id'))>0",
        f"json_type({dependency},'$.end_ordinal_exclusive')='integer'",
        f"json_extract({dependency},'$.end_ordinal_exclusive')>0",
        f"json_type({dependency},'$.end_byte_offset')='integer'",
        f"json_extract({dependency},'$.end_byte_offset')>=0",
    ])
    same_opening = " and ".join(f"json_extract({state},'$.history_dependencies[0].{field}')="
        f"json_extract({state},'$.root_metadata.history_base.{field}')"
        for field in ("thread_id", "end_ordinal_exclusive", "end_byte_offset"))
    return f"""case when json_valid({state}) then
        json_type({state}, '$')='object'
        and json_type({state}, '$.history_baseline_pending') in ('true','false')
        and json_type({state}, '$.history_boundary_digest')='text'
        and json_type({state}, '$.root_inline_replay_possible') in ('true','false')
        and json_type({state}, '$.history_dependencies')='array'
        and json_array_length({state}, '$.history_dependencies')<=32
        and not exists(select 1 from json_each({state},'$.history_dependencies') d
                       where not coalesce(({valid_dependencies}),0))
        and not exists(select 1 from json_each({state},'$.history_dependencies') d
                       group by lower(json_extract({dependency},'$.thread_id')) having count(*)>1)
        and (case when json_type({state}, '$.root_metadata.history_base')='object'
             then ({same_opening}) else json_array_length({state}, '$.history_dependencies')=0 end)
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
