from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from dataclasses import replace
from pathlib import Path

from codex_usage.agent_local_data import reset_local_data
from codex_usage.agent_paths import validate_codex_home
from codex_usage.agent_parent import start_parent_monitor
from codex_usage.agent_runtime import (
    AgentAlreadyRunningError,
    CodexUsageAgent,
)
from codex_usage.agent_service import (
    background_agent_status,
    install_background_agent,
    uninstall_background_agent,
)
from codex_usage.agent_settings import load_agent_settings, save_agent_settings


def build_agent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-usage-agent",
        description="Private Codex Usage native-app capture agent.",
    )
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--settings-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--capture-once", action="store_true", help=argparse.SUPPRESS)
    controls = parser.add_mutually_exclusive_group()
    controls.add_argument("--install-service", action="store_true", help=argparse.SUPPRESS)
    controls.add_argument("--uninstall-service", action="store_true", help=argparse.SUPPRESS)
    controls.add_argument("--service-status", action="store_true", help=argparse.SUPPRESS)
    controls.add_argument("--set-codex-home", type=Path, help=argparse.SUPPRESS)
    controls.add_argument(
        "--set-background-capture",
        choices=("true", "false"),
        help=argparse.SUPPRESS,
    )
    controls.add_argument("--reset-local-data", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--remove-settings", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_agent_parser().parse_args(argv)
    if args.install_service:
        return _print_control_result(install_background_agent().to_dict())
    if args.uninstall_service:
        return _print_control_result(uninstall_background_agent().to_dict())
    if args.service_status:
        return _print_control_result(background_agent_status().to_dict())
    if args.set_codex_home is not None:
        home = validate_codex_home(args.set_codex_home)
        settings = load_agent_settings(args.settings_file)
        save_agent_settings(
            replace(settings, codex_home=str(home)), args.settings_file
        )
        return _print_control_result({"codex_home": str(home)})
    if args.set_background_capture is not None:
        settings = load_agent_settings(args.settings_file)
        enabled = args.set_background_capture == "true"
        save_agent_settings(
            replace(settings, background_capture=enabled), args.settings_file
        )
        return _print_control_result({"background_capture": enabled})
    if args.reset_local_data:
        settings = load_agent_settings(args.settings_file)
        return _print_control_result(
            reset_local_data(
                Path(settings.codex_home),
                remove_settings=args.remove_settings,
                settings_file=args.settings_file,
            )
        )
    agent = CodexUsageAgent(settings_file=args.settings_file)
    try:
        agent.start(port=args.port)
    except AgentAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        return 0 if args.background else 2

    def stop_handler(_signum: int, _frame: object) -> None:
        agent.request_shutdown()

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            signal.signal(signal_value, stop_handler)
    parent_monitor_stop = threading.Event()
    parent_monitor = (
        start_parent_monitor(
            args.parent_pid,
            agent.request_shutdown,
            stop_event=parent_monitor_stop,
        )
        if args.parent_pid is not None
        else None
    )
    try:
        if args.capture_once:
            result = agent.capture_now().result()
            return 0 if result.outcome == "success" else 2
        agent.run_forever()
        return 0
    finally:
        parent_monitor_stop.set()
        if parent_monitor is not None:
            parent_monitor.join(timeout=2)
        agent.stop()


def _print_control_result(payload: dict[str, object]) -> int:
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
