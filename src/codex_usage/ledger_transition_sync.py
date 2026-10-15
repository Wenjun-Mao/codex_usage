"""Mirror parser-owned project transitions into the normalized ledger."""


def sync_transitions(connection):
    current = [tuple(row) for row in connection.execute("""select owner_task_id, source_key, source_label,
        target_key, target_label, effective_from, confidence, evidence_json, task_ids_json
        from ledger_transitions order by transition_id""")]
    desired = [(str(row["owner_thread_id"]), str(row["source_key"]), str(row["source_label"]),
        str(row["target_key"]), str(row["target_label"]), str(row["effective_from"]),
        int(row["confidence"]), str(row["evidence_json"]), str(row["thread_ids_json"]))
        for row in connection.execute("select * from project_transitions order by effective_from, source_key, target_key")]
    if current == desired:
        return False
    connection.execute("delete from ledger_transitions")
    connection.executemany("""insert into ledger_transitions(owner_task_id,source_key,source_label,
        target_key,target_label,effective_from,confidence,evidence_json,task_ids_json)
        values (?,?,?,?,?,?,?,?,?)""", desired)
    return True
