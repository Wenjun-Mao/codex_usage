"""Typed discovery decisions are scheduling hints, never accounting authority."""
from dataclasses import dataclass
from enum import StrEnum
import json

from codex_usage.checkpoint_history_contract import history_contract_sql

PREFIX = "history-upgrade:"
WAIT_PREFIX = "history-upgrade-wait:"
WAIT_ERROR = "stale append checkpoint: accounting_upgrade_dependency_pending"


class UpgradeDisposition(StrEnum):
    PENDING = "pending"
    UNCHANGED = "no-inherited-prefix"
    REBUILD = "rebuild"


class UpgradeReason(StrEnum):
    BUDGET = "budget"
    UNAVAILABLE = "unavailable"
    CHANGED = "changed"
    INVALID = "invalid-metadata"
    DEPENDENCY = "dependency"
    INHERITED = "inherited-history"
    NO_INHERITED_PREFIX = "no-inherited-prefix"


@dataclass(frozen=True, slots=True)
class UpgradeDiscovery:
    blocked: frozenset[str]
    bytes_read: int
    protected: frozenset[str] = frozenset()
    dependents: frozenset[str] = frozenset()


def decision(connection, source_key, *, waiting=False):
    row = connection.execute("select value from schema_meta where key=?",
                             ((WAIT_PREFIX if waiting else PREFIX)+source_key,)).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
        if type(value["version"]) is not int or value["version"] != 1:
            return None
        UpgradeDisposition(value["disposition"])
        UpgradeReason(value["reason"])
        if "attempt" in value and (type(value["attempt"]) is not int or value["attempt"] < 0):
            return None
        return value
    except (ValueError, KeyError, TypeError):
        return None


def store_decision(connection, source_key, value, *, waiting=False):
    connection.execute("insert or replace into schema_meta(key,value) values (?,?)",
        ((WAIT_PREFIX if waiting else PREFIX)+source_key, json.dumps({**value, "version": 1}, sort_keys=True)))


def rekey_upgrade_decision(connection, source_key, replacement_key):
    connection.execute("insert or replace into schema_meta(key,value) select ?,value from schema_meta where key=?",
                       (PREFIX+replacement_key, PREFIX+source_key))
    connection.execute("delete from schema_meta where key=?", (PREFIX+source_key,))


def pending_upgrade_keys(connection, *, budget_only=False):
    value = "(case when json_valid(m.value) then m.value else '{}' end)"
    reason = f"and json_extract({value},'$.reason')='budget'" if budget_only else ""
    rows = connection.execute(f"""select f.file_key from schema_meta m
        join files f on m.key=?||f.file_key
        left join parser_checkpoints p using(file_key)
        where f.is_missing=0 and json_valid(m.value)
          and json_extract({value},'$.version')=1
          and json_extract({value},'$.disposition')='pending' {reason}
          and not coalesce(({history_contract_sql()}),0)""", (PREFIX,)).fetchall()
    keys = {str(row[0]) for row in rows}
    if not budget_only:
        keys.update(str(row[0]) for row in connection.execute(f"""select f.file_key
            from schema_meta m join files f on m.key=?||f.file_key
            where f.is_missing=0 and json_valid(m.value)
              and json_extract({value},'$.version')=1
              and json_extract({value},'$.disposition')='pending'""", (WAIT_PREFIX,)))
    return keys
