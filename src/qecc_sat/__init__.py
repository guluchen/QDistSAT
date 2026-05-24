"""QEEC SAT: quantum error correction distance via SAT solvers."""

from pathlib import Path

__version__ = "0.2.0"

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
DEFAULT_MATRIX_DIR = REPO_ROOT / "data" / "matrices"
