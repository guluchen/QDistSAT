"""Repository portability and layout checks for published benchmark inputs."""

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
WINDOWS_FORBIDDEN = frozenset('<>:"\\|?*')
MATRIX_KINDS = ("Hx", "Hz", "Gx", "Gz")

# Tier membership of the stems shipped in this repository (see data/README.md).
# Stems listed in the cross-repo tier spec that exist only in DistQLDPC are not here.
EXPECTED_TIERS = {
    "tier0": ("BB_72_12_6", "BB_90_8_10", "GB_144_12_8", "LP_136_32_4", "LP_34_20_2", "TN_36_8_3", "TN_36_8_4", "TN_54_11_4", "TN_72_14_4", "TN_72_8_8"),
    "tier1": ("BB_108_8_10", "BB_144_12_12", "LP_238_44_6", "LP_340_56_8"),
    "tier2": ("BB_144_14_14", "LP_442_68_10", "TN_108_2_12"),
    "tier3": ("BB_288_12_18", "GB_144_12_12", "LP_544_80_12", "TN_144_2_13", "TN_200_10_10"),
    "tier4": ("TN_250_10_15",),
    "tier5": ("BB_360_12_17to24", "LP_1768_224_ge17", "LP_714_100_16", "TN_360_4_ge17"),
}
FORMER_BATCH_DIRS = ("BB", "BB2", "LP", "LP2", "QT", "QT2")


def _shipped_stems():
    stems = {}
    for hx in sorted(DATA_ROOT.rglob("*_Hx.txt")):
        stems.setdefault(hx.name[: -len("_Hx.txt")], []).append(hx.parent)
    return stems


def test_benchmark_matrix_paths_are_windows_compatible():
    invalid = [
        str(path.relative_to(REPO_ROOT))
        for path in DATA_ROOT.rglob("*")
        if any(char in WINDOWS_FORBIDDEN for char in path.name)
    ]
    assert invalid == []


def test_matrix_stems_live_in_expected_tier_with_all_matrices():
    missing = [
        str(DATA_ROOT / tier / f"{stem}_{kind}.txt")
        for tier, stems in EXPECTED_TIERS.items()
        for stem in stems
        for kind in MATRIX_KINDS
        if not (DATA_ROOT / tier / f"{stem}_{kind}.txt").is_file()
    ]
    assert missing == []


def test_every_shipped_stem_is_in_exactly_one_known_tier():
    expected = {stem: tier for tier, stems in EXPECTED_TIERS.items() for stem in stems}
    shipped = _shipped_stems()
    misplaced = {
        stem: [str(p.relative_to(DATA_ROOT)) for p in parents]
        for stem, parents in shipped.items()
        if [p.name for p in parents] != [expected.get(stem)]
        or any(p.parent != DATA_ROOT for p in parents)
    }
    assert misplaced == {}
    assert sorted(shipped) == sorted(expected)


def test_data_root_has_only_tier_subdirectories():
    subdirs = sorted(p.name for p in DATA_ROOT.iterdir() if p.is_dir())
    assert subdirs == sorted(EXPECTED_TIERS)
    assert not any((DATA_ROOT / name).exists() for name in FORMER_BATCH_DIRS)
    assert not any(DATA_ROOT.rglob("QT_*")), "QT_* stems were renamed to TN_*"


def _load_compare_harness():
    path = REPO_ROOT / "benchmarks" / "compare_distqldpc_binaries.py"
    spec = importlib.util.spec_from_file_location("compare_distqldpc_binaries", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve annotations via sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "stem,tier",
    [("LP_136_32_4", "tier0"), ("BB_108_8_10", "tier1"), ("TN_360_4_ge17", "tier5")],
)
def test_distqldpc_compare_harness_finds_stems_in_tiers(stem, tier):
    # DistQLDPC's cross-repo CI calls the harness with --data-root <QDistSAT>/data.
    harness = _load_compare_harness()
    assert harness.matrix_prefix(DATA_ROOT, stem) == DATA_ROOT / tier / stem
    assert harness.matrix_prefix(DATA_ROOT / tier, stem) == DATA_ROOT / tier / stem


def test_distqldpc_compare_harness_rejects_unknown_stem():
    harness = _load_compare_harness()
    with pytest.raises(SystemExit):
        harness.matrix_prefix(DATA_ROOT, "QT_36_8_4")
