"""Compare a frozen engine and DLL with its qualified private build runtime."""
import argparse
import json
from pathlib import Path
import subprocess

from codex_usage.sqlite_runtime import require_release_runtime


def verify(executable, output):
    expected = require_release_runtime()
    result = json.loads(subprocess.check_output([str(executable), '--sqlite-runtime'],
                                              text=True, timeout=30))
    for key in ('version', 'source_id', 'compile_options'):
        if result[key] != expected[key]:
            raise ValueError(f'Frozen SQLite identity differs: {key}')
    if expected.get('library_sha256') != result.get('library_sha256'):
        raise ValueError('Frozen SQLite DLL differs from its private build runtime')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.executable, args.output)))
