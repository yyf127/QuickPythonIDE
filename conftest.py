"""Ensure the repository root is importable so tests can `from main import Api`.

pytest's default import mode puts the test directory (tests/) on sys.path, not the
repo root. This conftest inserts the root so `main` is always importable, regardless
of how pytest is invoked (console script vs `python -m pytest`).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
