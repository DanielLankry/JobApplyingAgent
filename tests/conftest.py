"""Test fixtures for the job-agent test suite."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _clear_env(*keys):
    for k in keys:
        os.environ.pop(k, None)
