"""One accounting projection per physical source, separate from parser ownership."""
import json

PREFIX = "retained-accounting:"
PROJECTION_VERSION = 1


def receipts(connection):
    return [json.loads(row[0]) for row in connection.execute(
        "select value from schema_meta where key like ?", (PREFIX+"%",))]


def _bound_families_sql():
    return f"""select a.key from schema_meta a where a.key like '{PREFIX}%'
        and json_extract(a.value,'$.version')=1
        and json_extract(a.value,'$.projection')={PROJECTION_VERSION}
        and not exists (
            select 1 from json_each(a.value,'$.bindings') m
            left join files af on af.file_key=json_extract(m.value,'$.key')
            left join parser_checkpoints ac on ac.file_key=af.file_key
            where af.file_key is null or ac.file_key is null
              or ac.byte_offset!=json_extract(m.value,'$.offset')
              or ac.next_record_index!=json_extract(m.value,'$.count')
              or ac.head_sha256!=json_extract(m.value,'$.head')
              or ac.boundary_sha256!=json_extract(m.value,'$.boundary')
              or cast(ac.source_device as integer)!=json_extract(m.value,'$.device')
              or cast(ac.source_inode as integer)!=json_extract(m.value,'$.inode')
              or af.parsed_at!=json_extract(m.value,'$.parsed_at')
              or ac.session_id is not json_extract(m.value,'$.session_id')
              or json_extract(ac.state_json,'$.root_metadata') is not json_extract(m.value,'$.root_json')
              or json_extract(ac.state_json,'$.history_boundary_digest') is not json_extract(m.value,'$.history_boundary')
              or json_extract(ac.state_json,'$.root_session_id') is not json_extract(m.value,'$.root_session_id')
              or json_extract(ac.state_json,'$.root_session_is_fork') is not json_extract(m.value,'$.root_fork')
              or json_extract(ac.state_json,'$.root_inline_replay_possible') is not json_extract(m.value,'$.inline_replay'))"""


def selected_sql():
    # Unqualified families are withheld, never restored to additive accounting.
    return f"""select json_extract(chosen.value,'$.selected') from schema_meta chosen
        where chosen.key in ({_bound_families_sql()}) and json_extract(chosen.value,'$.status')='selected'
        and json_type(chosen.value,'$.bindings')='array' and json_array_length(chosen.value,'$.bindings')>0
        and exists (select 1 from json_each(chosen.value,'$.bindings') b
            where json_extract(b.value,'$.key')=json_extract(chosen.value,'$.selected'))
        and exists (select 1 from json_each(chosen.value,'$.members') m
            where json_extract(m.value,'$.key')=json_extract(chosen.value,'$.selected'))"""


def members_sql(*, bound_only=False):
    bound = f"and a.key in ({_bound_families_sql()})" if bound_only else ""
    return f"""select json_extract(m.value,'$.key') from schema_meta a,
        json_each(a.value,'$.members') m where a.key like '{PREFIX}%' {bound}"""


def accounting_predicate(alias):
    return f"({alias}.file_key not in ({members_sql()}) or {alias}.file_key in ({selected_sql()}))"


def accounting_keys(connection, keys, excluded=()):
    members = {row[0] for row in connection.execute(members_sql())}
    # A cache-only database has no normalized projection to bind yet.
    if not receipts(connection):
        return keys-set(excluded)
    selected = {row[0] for row in connection.execute(selected_sql())}
    return (keys-members-set(excluded)) | (keys & selected)


def source_selection(connection):
    if not receipts(connection):
        return set(), set()
    return ({row[0] for row in connection.execute(members_sql(bound_only=True))},
            {row[0] for row in connection.execute(selected_sql())})


def issues(connection):
    result = {}
    for receipt in receipts(connection):
        if receipt["status"] == "quarantined" or receipt.get("unresolved"):
            for member in receipt["members"]:
                row = connection.execute("select path from files where file_key=?", (member["key"],)).fetchone()
                if row is not None:
                    result[row[0]] = "PaginatedHistoryError: paginated_accounting_"+receipt["reason"]
    return result
