"""Read account metadata without authentication retention or model requests."""
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from codex_usage.allowance_models import QuotaObservation, identifier, integer, quota_observations
from codex_usage.app_server_rpc import AppServerRpc, RpcError
from codex_usage.codex_registration import discover_codex_executables


@dataclass(frozen=True, slots=True)
class QuotaRead:
    timestamp: str
    plan: str = ""
    observations: tuple[QuotaObservation, ...] = ()
    lifetime_tokens: int | None = None
    diagnostics: str = ""


def probe_allowance(codex_home: Path, *, timeout: float = 8) -> QuotaRead:
    stamp = datetime.now(UTC).isoformat()
    deadline = monotonic() + timeout
    for executable in discover_codex_executables():
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        try:
            with AppServerRpc(executable, codex_home, timeout=remaining) as rpc:
                results = {}
                errors = []
                for method, params in (
                    ("account/read", {"refreshToken": False}),
                    ("account/rateLimits/read", {}),
                    ("account/usage/read", {}),
                ):
                    try:
                        results[method] = rpc.call(method, params)
                    except RpcError as exc:
                        errors.append(f"{method}:{exc}")
                account = results.get("account/read", {}).get("account")
                plan = identifier(account.get("planType")) if isinstance(account, dict) else ""
                observations = quota_observations(results.get("account/rateLimits/read"), stamp, plan=plan)
                summary = results.get("account/usage/read", {}).get("summary")
                lifetime = integer(summary.get("lifetimeTokens")) if isinstance(summary, dict) else None
                if not observations:
                    errors.append("quota_unavailable")
                return QuotaRead(stamp, plan, observations, lifetime, ";".join(errors))
        except (OSError, RpcError):
            continue
    return QuotaRead(stamp, diagnostics="probe_unavailable")
