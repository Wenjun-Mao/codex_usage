"""The packaged engine probe must not initialize an agent or read settings."""
import json
from unittest.mock import patch

from codex_usage.agent_main import main
from codex_usage.sqlite_runtime import RELEASE_SOURCE_ID, RELEASE_VERSION


def test_runtime_probe_is_memory_only(capsys):
    with (patch('codex_usage.agent_runtime.CodexUsageAgent', side_effect=AssertionError('agent started')),
          patch('codex_usage.agent_settings.load_agent_settings', side_effect=AssertionError('settings read'))):
        assert main(['--sqlite-runtime']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['version'] == RELEASE_VERSION
    assert result['source_id'] == RELEASE_SOURCE_ID
