"""Load repository CLI modules through their normal scripts import root."""
import importlib
from pathlib import Path
import sys


def load_tool(name):
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module(name)
