from __future__ import annotations

import multiprocessing


if __name__ == "__main__":
    multiprocessing.freeze_support()
    from codex_usage.cli import main

    raise SystemExit(main())
