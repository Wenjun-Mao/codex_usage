"""Run pure publisher guards without credentials, CI or network."""
from pathlib import Path
import subprocess


def test_publisher_hash_guards_and_partial_release_states():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "--test", str(root / "tests/release_publication.test.cjs"),
        str(root / "tests/release_publisher_entrypoint.test.cjs")],
        cwd=root, check=True, capture_output=True)
