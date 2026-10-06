from pathlib import Path
import sys

import pytest

from probe import tunnel


class ExecCalled(Exception):
    pass


@pytest.fixture
def local_setup(monkeypatch, tmp_path):
    client = tmp_path / "tunnel-client"
    client.touch()
    config = tmp_path / ".env"
    config.write_text("CODEX_USAGE_TUNNEL_ID=tunnel_test\nCONTROL_PLANE_API_KEY=synthetic-sentinel\n")
    config.chmod(0o600)
    monkeypatch.setattr(tunnel, "ROOT", tmp_path)
    monkeypatch.setattr(tunnel, "DEFAULT_CLIENT", client)
    return config


@pytest.mark.parametrize("action", ["run", "doctor"])
def test_credential_is_env_only_and_tunnel_is_explicit(monkeypatch, local_setup, action):
    monkeypatch.setattr(sys, "argv", ["tunnel", action])
    monkeypatch.setenv("HARPOON_TARGETS", "must-not-be-inherited")
    monkeypatch.setenv("LOG_HTTP_RAW_UNSAFE", "true")
    monkeypatch.setenv("CONTROL_PLANE_API_KEY", "unrelated-key")
    calls = []

    def execute(path, args, env):
        calls.append((path, args, env))
        raise ExecCalled

    monkeypatch.setattr(tunnel.os, "execve", execute)
    with pytest.raises(ExecCalled):
        tunnel.main()
    path, args, env = calls[0]
    assert Path(path).name == "tunnel-client"
    assert "synthetic-sentinel" not in " ".join(args)
    assert env["CONTROL_PLANE_API_KEY"] == "synthetic-sentinel"
    assert "HARPOON_TARGETS" not in env
    assert "LOG_HTTP_RAW_UNSAFE" not in env
    assert args[args.index("--control-plane.tunnel-id") + 1] == "tunnel_test"


def test_missing_key_fails_without_echoing_config(monkeypatch, local_setup, capsys):
    local_setup.write_text("CODEX_USAGE_TUNNEL_ID=tunnel_test\nCONTROL_PLANE_API_KEY=\n")
    monkeypatch.setattr(sys, "argv", ["tunnel", "run"])
    with pytest.raises(SystemExit) as error:
        tunnel.main()
    assert error.value.code == 2
    assert "do not paste it into chat" in capsys.readouterr().err


@pytest.mark.skipif(tunnel.os.name != "posix", reason="POSIX credential file permissions")
def test_shared_credential_file_rejected(monkeypatch, local_setup, capsys):
    local_setup.chmod(0o644)
    monkeypatch.setattr(sys, "argv", ["tunnel", "run"])
    with pytest.raises(SystemExit):
        tunnel.main()
    err = capsys.readouterr().err
    assert "chmod 600 .env" in err
    assert "synthetic-sentinel" not in err
