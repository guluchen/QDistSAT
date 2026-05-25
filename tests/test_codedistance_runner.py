"""codeDistance optional comparison solver ids (no pip package required)."""

from qecc_sat.codedistance_runner import (
    CODEDISTANCE_BENCH_CONFIGS,
    CODEDISTANCE_SOLVER,
    codedistance_solver_id,
    explain_codedistance_failure,
    expand_codedistance_solver_requests,
    is_codedistance_solver,
    resolve_codedistance_config_id,
)


def test_bench_config_methods():
    methods = [m for _, m, _ in CODEDISTANCE_BENCH_CONFIGS]
    assert methods == ["GurobiDist", "MIPDist", "dist_m4ri_CC", "magmaMinWord"]


def test_mip_scip_params():
    row = next(x for x in CODEDISTANCE_BENCH_CONFIGS if x[0] == "mip-scip")
    assert row[2] == {"MIP_solver": "SCIP"}


def test_expand_codedistance_umbrella():
    out = expand_codedistance_solver_requests(["codedistance", "rc2-g3"])
    assert out[:4] == [
        "cd-gurobi",
        "cd-mip-scip",
        "cd-m4ri-cc",
        "cd-magma",
    ]
    assert out[4] == "rc2-g3"


def test_explain_dist_m4ri_and_magma_errors():
    s, d = explain_codedistance_failure(
        "m4ri-cc", "[Errno 2] No such file or directory: 'dist_m4ri'"
    )
    assert "not installed" in s
    assert "install_dist_m4ri" in d
    # Runtime errors must not be mislabeled as missing binary.
    s2, _ = explain_codedistance_failure("m4ri-cc", "KeyError('LOCheck')")
    assert "not installed" not in s2
    s2, d2 = explain_codedistance_failure(
        "magma", "[Errno 2] No such file or directory: 'magma'"
    )
    assert "magma" in s2.lower()
    assert "Magma" in d2


def test_resolve_and_is_codedistance():
    assert resolve_codedistance_config_id("cd-gurobi") == "gurobi"
    assert resolve_codedistance_config_id("gurobi") == "gurobi"
    assert resolve_codedistance_config_id("codedistance") is None
    assert resolve_codedistance_config_id("cd-nope") is None
    assert is_codedistance_solver("cd-magma")
    assert is_codedistance_solver(CODEDISTANCE_SOLVER)
    assert not is_codedistance_solver("maxcdcl")
    assert codedistance_solver_id("m4ri-cc") == "cd-m4ri-cc"
