"""Fail package construction if its Python would bundle an older SQLite."""
import json

from codex_usage.sqlite_runtime import require_release_runtime


if __name__ == "__main__":
    print(json.dumps(require_release_runtime(), indent=2))
