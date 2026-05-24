"""MaxSAT manifest and output parsing."""

import platform

import pytest

from qecc_sat.maxsat_external import parse_cominisatps_optimal, parse_o_v_lines
from qecc_sat.maxsat_registry import (
    get_spec,
    host_supports_linux_elf,
    is_installed,
    list_status,
    load_manifest,
    maxsat_runnable_on_host,
)


def test_manifest_loads():
    specs = load_manifest()
    ids = {s.id for s in specs}
    assert "cashw-coreplus" in ids
    assert "evalmaxsat" in ids
    assert "maxcdcl" in ids
    assert "glucose_release" in ids


def test_parse_o_v_lines():
    text = "c comment\no 6\nv 1 -2 3 0\n"
    cost, model = parse_o_v_lines(text)
    assert cost == 6
    assert model == [1, -2, 3]


def test_get_spec_cashw():
    spec = get_spec("cashw-coreplus")
    assert "cashwmaxsatcoreplus" in spec.executable_relpath
    assert spec.linux_elf


def test_get_spec_evalmaxsat():
    spec = get_spec("evalmaxsat")
    assert spec.executable_relpath.endswith("EvalMaxSAT")
    assert spec.output_format == "o_v_lines"


def test_get_spec_glucose_release_flat():
    spec = get_spec("glucose_release")
    assert spec.install_layout == "flat"
    assert spec.output_format == "cominisatps_optimal"
    assert spec.executable_path().name == "glucose_release"


def test_parse_cominisatps_optimal():
    text = "c initCost: 0, fixedBySearch: 0, optimal: 3, maxsat: 2\ns SATISFIABLE\n"
    cost, model = parse_cominisatps_optimal(text)
    assert cost == 3
    assert model is None


def test_glucose_release_runnable_if_installed():
    if not is_installed("glucose_release"):
        pytest.skip("glucose_release binary not present")
    assert maxsat_runnable_on_host("glucose_release")


def test_linux_elf_not_runnable_off_linux():
    if host_supports_linux_elf():
        pytest.skip("linux host")
    assert not maxsat_runnable_on_host("cashw-coreplus")
    assert not maxsat_runnable_on_host("evalmaxsat")
    row = next(r for r in list_status() if r["id"] == "cashw-coreplus")
    if row["installed"]:
        assert row.get("skipped_host")
        assert row["error"] is None


def test_cashw_platform_on_darwin():
    from qecc_sat.maxsat_registry import MaxSATPlatformError, resolve_executable

    if platform.system() == "Linux":
        pytest.skip("linux host")
    if not any(r["installed"] for r in list_status() if r["id"] == "cashw-coreplus"):
        pytest.skip("cashw-coreplus not installed")
    exe = resolve_executable("cashw-coreplus")
    with pytest.raises(MaxSATPlatformError, match="unsupported platform"):
        from qecc_sat.maxsat_registry import assert_runnable

        assert_runnable(exe)
