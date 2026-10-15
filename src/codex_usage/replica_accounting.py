"""Reconcile retained accounting facts without changing parser checkpoints."""
from dataclasses import asdict
import json
from pathlib import Path

from codex_usage.replica_accounting_proof import (
    AccountingProofError, capture_binding, digest, dominant_capture, load_accounting_capture,
)
from codex_usage.replica_accounting_selection import PREFIX, PROJECTION_VERSION
from codex_usage.replica_accounting_selection import receipts, source_selection
from codex_usage.session_cache_requests import load_cached_rows
from codex_usage.session_history_models import PaginatedHistoryError
from codex_usage.session_replica_retention import (
    ALIAS_PREFIX, cached_replica_families, retained_family_state,
)
from codex_usage.session_rollout_identity import rollout_identity
from codex_usage.session_cache_source_identity import known_physical_identity
from codex_usage.session_history import PAGE_KEY_PREFIX


def reconcile_accounting(connection):
    """Revalidate actual facts at capture/sync boundaries, not on range reads."""
    owned = not connection.in_transaction
    if owned:
        connection.execute("begin immediate")
    try:
        changed = _reconcile(connection)
        if owned:
            if changed and _has_ledger(connection):
                from codex_usage.ledger_schema import increment_ledger_revision
                from codex_usage.speed_store import synchronize_speed
                increment_ledger_revision(connection)
                synchronize_speed(connection, usage_changed=True)
            connection.commit()
        return changed
    except BaseException:
        if owned:
            connection.rollback()
        raise


def _reconcile(connection):
    old = {row["key"]: row["value"] for row in connection.execute(
        "select key,value from schema_meta where key like ?", (PREFIX+"%",))}
    current, changed = {}, False
    rows = load_cached_rows(connection)
    groups = cached_replica_families(_captured_rows(connection, rows))
    previous = {}
    for value in old.values():
        receipt = json.loads(value)
        physical_id = receipt.get("physical_id")
        if physical_id is None:
            identities = [rollout_identity(Path(rows[m["key"]]["path"]))
                          for m in receipt["members"] if m["key"] in rows]
            physical_id = next((i.rollout_id for i in identities if i is not None), None)
        if physical_id is None:
            continue
        previous[physical_id] = receipt
        group = groups.setdefault(physical_id, {})
        group.update({m["key"]: rows[m["key"]] for m in receipt["members"] if m["key"] in rows})
    for physical_id, group in groups.items():
        prior = previous.get(physical_id)
        family = retained_family_state(connection, physical_id, group)
        keys = {key for key, _ in family}
        identity = known_physical_identity(connection, physical_id)
        declared_page_key = PAGE_KEY_PREFIX+physical_id
        if prior is None and (len(group) < 2 or (not family and identity is None and declared_page_key not in group)):
            continue
        physical_key = (prior["physical_key"] if prior else sorted(keys)[0] if keys else
                        identity["canonical_key"] if identity is not None else declared_page_key)
        if (len(family) == len(group) and len(keys) == 1 and _byte_proven(connection, physical_key, family)
                and (prior is None or _prior_byte_covered(connection, prior, family))):
            continue
        eligible = {r.row["file_key"]: r for key, r in family if key == physical_key}
        member_keys = set(group) | ({m["key"] for m in prior["members"]} if prior else set())
        members = [capture_binding(eligible[key]) if key in eligible else dict(key=key, unavailable=True)
                   for key in sorted(member_keys)]
        receipt = dict(version=1, projection=PROJECTION_VERSION, physical_id=physical_id, physical_key=physical_key, members=members,
            bindings=[], status="quarantined", selected=None, reason="incomparable_captures")
        try:
            if set(eligible) != member_keys or len(keys) != 1:
                raise AccountingProofError("malformed_family_member")
            captures = [load_accounting_capture(connection, physical_key, eligible[key]) for key in sorted(eligible)]
            winner = dominant_capture(captures)
            receipt.update(status="selected", selected=winner.key, reason="stored_fact_prefix",
                members=[capture.binding for capture in captures], bindings=[capture.binding for capture in captures],
                facts={c.key: dict(cache=digest(c.cache), normalized=digest(c.normalized),
                    lineage=digest(c.lineage)) for c in captures})
        except (AccountingProofError, PaginatedHistoryError) as error:
            receipt["reason"] = str(error)
            _retain_prior(connection, prior, physical_key, eligible, receipt)
        if _has_ledger(connection):
            for key in member_keys:
                generation = connection.execute("""select g.* from ledger_generations g
                    join ledger_sources s using(source_id) where s.source_key=?
                    order by g.generation_number desc limit 1""", (key,)).fetchone()
                if generation is None:
                    continue
                status = ("trusted" if key == receipt["selected"] else
                          "superseded" if receipt["status"] == "selected" and not receipt.get("unresolved") else "staging")
                if generation["status"] != status:
                    connection.execute("update ledger_generations set status=? where generation_id=?",
                                       (status, generation["generation_id"]))
                    changed = True
        value = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        current[PREFIX+physical_key] = value
    for key in old.keys()-current.keys():
        connection.execute("delete from schema_meta where key=?", (key,))
        changed = True
    for key, value in current.items():
        if old.get(key) != value:
            connection.execute("insert or replace into schema_meta(key,value) values (?,?)", (key, value))
            changed = True
    changed |= _refresh_coverage(connection, current)
    return changed


def _captured_rows(connection, rows):
    captured = {}
    normalized = _has_ledger(connection)
    for key, row in rows.items():
        has_facts = row["checkpoint_offset"] is not None
        if not has_facts:
            has_facts = any(connection.execute(f"select 1 from {table} where file_key=? limit 1", (key,)).fetchone()
                            for table in ("usage_records", "image_operations"))
        if not has_facts and normalized:
            has_facts = connection.execute("""select 1 from ledger_sources s join ledger_generations g using(source_id)
                where s.source_key=? limit 1""", (key,)).fetchone() is not None
        if has_facts:
            captured[key] = row
    return captured


def _retain_prior(connection, prior, physical_key, eligible, receipt):
    if (prior is None or prior.get("version") != 1 or prior.get("projection") != PROJECTION_VERSION
            or prior.get("selected") not in eligible):
        return
    key = prior["selected"]
    try:
        capture = load_accounting_capture(connection, physical_key, eligible[key])
    except (AccountingProofError, PaginatedHistoryError):
        return
    facts = dict(cache=digest(capture.cache), normalized=digest(capture.normalized), lineage=digest(capture.lineage))
    if facts != prior.get("facts", {}).get(key):
        return
    receipt.update(status="selected", selected=key, unresolved=True, bindings=[capture.binding],
        facts={key: facts}, last_complete_proof=prior.get("last_complete_proof", dict(
            selected=prior["selected"], members=prior["members"], facts=prior.get("facts", {}))))


def _prior_byte_covered(connection, prior, family):
    owner = next((r for _, r in family if r.row["file_key"] == prior["physical_key"]), None)
    if owner is None:
        return False
    for member in prior["members"]:
        if member["key"] == prior["physical_key"]:
            continue
        row = connection.execute("select value from schema_meta where key=?", (ALIAS_PREFIX+member["key"],)).fetchone()
        if row is None or "offset" not in member:
            return False
        alias = json.loads(row[0])
        prefix = dict(byte_offset=member["offset"], head_sha256=member["head"], boundary_sha256=member["boundary"])
        if alias["owner_key"] != prior["physical_key"] or prefix not in alias["prefixes"]:
            return False
        if owner.checkpoint.byte_offset < member["offset"]:
            return False
    return True


def _refresh_coverage(connection, current):
    if not _has_ledger(connection):
        return False
    changed = False
    for value in current.values():
        receipt = json.loads(value)
        for member in receipt["members"]:
            row = connection.execute("""select s.source_id, s.error, f.error file_error
                from ledger_sources s join files f on f.file_key=s.source_key
                where f.file_key=?""", (member["key"],)).fetchone()
            if row is None:
                continue
            error = row["file_error"] or ""
            if receipt["status"] == "quarantined" or receipt.get("unresolved"):
                error = "PaginatedHistoryError: paginated_accounting_"+receipt["reason"]
            if row["error"] != error:
                connection.execute("update ledger_sources set is_stale=?, error=?, stale_reason=? where source_id=?",
                    (int(bool(error)), error, error, row["source_id"]))
                changed = True
    return changed


def _byte_proven(connection, owner_key, family):
    owner = next((replica for key, replica in family if replica.row["file_key"] == owner_key), None)
    if owner is None:
        return False
    for _, replica in family:
        if replica.row["file_key"] == owner_key:
            continue
        row = connection.execute("select value from schema_meta where key=?",
                                 (ALIAS_PREFIX+replica.row["file_key"],)).fetchone()
        if row is None:
            return False
        receipt = json.loads(row[0])
        prefix = asdict(replica.prefixes[0])
        if (receipt["owner_key"] != owner_key or prefix not in receipt["prefixes"]
                or owner.checkpoint.byte_offset < max(p["byte_offset"] for p in receipt["prefixes"])):
            return False
    return True


def _has_ledger(connection):
    return connection.execute("select 1 from sqlite_master where name='ledger_generations'").fetchone() is not None


def authorize_retained_snapshot(connection, source_key):
    """Authorize normalization of already-captured facts, never a raw read."""
    _, selected = source_selection(connection)
    if source_key not in selected:
        raise AccountingProofError("retained_snapshot_not_selected")
    receipt = next(r for r in receipts(connection) if r["selected"] == source_key)
    rows = load_cached_rows(connection)
    row = rows[source_key]
    identity = rollout_identity(Path(row["path"]))
    if identity is None:
        raise AccountingProofError("retained_snapshot_identity_unavailable")
    physical = identity.rollout_id
    family = retained_family_state(connection, physical, {source_key: row})
    if len(family) != 1:
        raise AccountingProofError("retained_snapshot_checkpoint_unavailable")
    capture = load_accounting_capture(connection, receipt["physical_key"], family[0][1])
    facts = receipt["facts"][source_key]
    if (digest(capture.cache), digest(capture.normalized), digest(capture.lineage)) != (
            facts["cache"], facts["normalized"], facts["lineage"]):
        raise AccountingProofError("retained_snapshot_facts_changed")
    return capture
