from qecc_sat.distance.compute_css_split_distance import (
    min_distance_quantum_css_split_or_logicals,
    split_css_stabilizers,
)
from qecc_sat.io import build_s_from_hx_hz, load_matrix, resolve_precomputed_logical_basis
from qecc_sat.sat_solver import SolverType

from tests.matrix_stem import BENCHMARK_D, BENCHMARK_STEM, MATRIX_DIR


def test_split_css_stabilizers_tn_36_8_4():
    hx = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"))
    hz = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hz.txt"))
    s = build_s_from_hx_hz(hx, hz)

    assert split_css_stabilizers(s, len(hx[0])) == (hx, hz)


def test_css_split_or_logicals_smoke_tn_36_8_4():
    hx = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"))
    hz = load_matrix(str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hz.txt"))
    logical, _, err = resolve_precomputed_logical_basis(
        str(MATRIX_DIR / f"{BENCHMARK_STEM}_Hx.txt"), len(hx[0])
    )
    assert err != "incomplete"

    d = min_distance_quantum_css_split_or_logicals(
        hx,
        hz,
        solver_type=SolverType.MINISAT22,
        max_distance=BENCHMARK_D,
        logical_basis_override=logical,
    )
    assert d == BENCHMARK_D


def test_css_split_reuses_one_sector_when_hx_equals_hz():
    h = [[1, 1, 0, 0]]
    stats = {}
    sector_records = {}

    d = min_distance_quantum_css_split_or_logicals(
        h,
        h,
        solver_type=SolverType.MINISAT22,
        max_distance=1,
        sector_cardinality="linear",
        stats=stats,
        per_sector_k_records=sector_records,
    )

    assert d == 1
    assert stats["css_d_Z"] == 1
    assert stats["css_d_X"] == 1
    assert stats["css_split_reused_symmetric_sector"] is True
    assert "z" in sector_records
    assert "x" not in sector_records
