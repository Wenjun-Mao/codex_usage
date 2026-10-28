"""The released ledger connection owns TEMP until completion on every exit."""
from concurrent.futures import CancelledError
import sqlite3

import pytest

from codex_usage.ledger_schema import open_ledger


@pytest.mark.parametrize('failure', [None, RuntimeError, CancelledError])
def test_temp_lives_through_commit_and_connection_closes_on_every_exit(tmp_path, failure):
    path = tmp_path / 'ledger.sqlite3'

    def operation():
        with open_ledger(path) as db:
            captured.append(db)
            db.execute('create temp table request_owned(value)')
            db.execute('insert into request_owned values (123)')
            db.commit()
            assert db.execute('select value from temp.request_owned').fetchone()[0] == 123
            if failure is not None:
                raise failure('synthetic request exit')

    captured = []
    if failure is None:
        operation()
    else:
        with pytest.raises(failure, match='synthetic request exit'):
            operation()
    with pytest.raises(sqlite3.ProgrammingError, match='closed database'):
        captured[0].execute('select * from temp.request_owned')
    with open_ledger(path, read_only=True) as db:
        assert db.execute('select count(*) from temp.sqlite_master').fetchone()[0] == 0
