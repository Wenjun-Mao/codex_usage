"""The serialized lineage contract distinguishes resume authority from old evidence."""
import json

import pytest

from codex_usage.checkpoint_history_contract import supports_history_resume
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_schema import open_ledger
from codex_usage.session_parser_models import parser_state_from_json
from test_history_dependency_invalidation import KEY, capture
from test_paginated_history import THREAD, corpus
from test_paginated_upgrade_rebuild import finish


@pytest.mark.parametrize("invalid", [None, [], {}, [{"thread_id": "bad"}], "different-opening", "duplicate"])
def test_malformed_or_mismatched_dependency_contract_never_grants_resume(tmp_path, invalid):
    home = tmp_path / "home"
    _, page, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    with open_ledger(ledger) as connection:
        state = json.loads(connection.execute("select state_json from parser_checkpoints where file_key=?", (KEY,)).fetchone()[0])
        dependencies = state["history_dependencies"]
        if invalid == "different-opening":
            invalid = [dict(dependencies[0], end_ordinal_exclusive=3)]
        elif invalid == "duplicate":
            invalid = [*dependencies, dict(dependencies[0], thread_id=THREAD.upper())]
        state["history_dependencies"] = invalid
        raw = json.dumps(state)
        connection.execute("update parser_checkpoints set state_json=? where file_key=?", (raw, KEY))
        assert not supports_history_resume(connection, KEY)
        with pytest.raises(ValueError):
            parser_state_from_json(raw, page)


def test_pre_dependency_checkpoint_is_readable_but_needs_bounded_upgrade(tmp_path):
    home = tmp_path / "home"
    _, page, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    with open_ledger(ledger) as connection:
        state = json.loads(connection.execute("select state_json from parser_checkpoints where file_key=?", (KEY,)).fetchone()[0])
        state.pop("history_dependencies")
        raw = json.dumps(state)
        assert parser_state_from_json(raw, page).history_dependencies == ()
        connection.execute("update parser_checkpoints set state_json=? where file_key=?", (raw, KEY))
        assert not supports_history_resume(connection, KEY)
        connection.commit()
    capture(home)
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select state_json from parser_checkpoints where file_key=?", (KEY,)).fetchone()[0] == raw
        assert "accounting_upgrade_required" in connection.execute("select error from files where file_key=?", (KEY,)).fetchone()[0]
    assert finish(home, source_key=KEY)[-1].complete
    with open_ledger(ledger, read_only=True) as connection:
        assert supports_history_resume(connection, KEY)
