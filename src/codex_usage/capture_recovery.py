"""Share the existing four historical I/O slots without adding capture work."""
from codex_usage.image_backfill import run_image_backfill_slice
from codex_usage.speed_recovery import run_speed_recovery_slice


def run_historical_recovery(codex_home, ledger_path):
    image = run_image_backfill_slice(codex_home, ledger_path)
    image_changed = image.changed
    speed = run_speed_recovery_slice(ledger_path)
    # Both domains always receive a slot; unused slots serve remaining work.
    for _ in range(2):
        if image.pending_tasks:
            image = run_image_backfill_slice(codex_home, ledger_path)
            image_changed |= image.changed
        else:
            speed = speed.plus(run_speed_recovery_slice(ledger_path))
    return image_changed, speed
