"""Repository portability checks for published benchmark inputs."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
WINDOWS_FORBIDDEN = frozenset('<>:"\\|?*')
UNKNOWN_DISTANCE_STEMS = (
    ("BB", "BB_360_12_unknown"),
    ("BB2", "BB_288_12_unknown"),
    ("LP2", "LP_1768_224_unknown"),
    ("LP2", "LP_714_100_unknown"),
    ("QT2", "TN_360_4_unknown"),
)


def test_benchmark_matrix_paths_are_windows_compatible():
    invalid = [
        str(path.relative_to(REPO_ROOT))
        for path in DATA_ROOT.rglob("*")
        if any(char in WINDOWS_FORBIDDEN for char in path.name)
    ]
    assert invalid == []


def test_unknown_distance_matrix_stems_are_complete():
    missing = [
        str(DATA_ROOT / batch / f"{stem}_{kind}.txt")
        for batch, stem in UNKNOWN_DISTANCE_STEMS
        for kind in ("Hx", "Hz", "Gx", "Gz")
        if not (DATA_ROOT / batch / f"{stem}_{kind}.txt").is_file()
    ]
    assert missing == []
