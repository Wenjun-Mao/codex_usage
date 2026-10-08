"""Load the shared, public acceptance fixture without changing package paths."""
from pathlib import Path
from runpy import run_path

_fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "observed_speed_fixture.py"))
AT = _fixture["AT"]
append_rows = _fixture["append_rows"]
response = _fixture["response"]
write_source = _fixture["write_source"]
