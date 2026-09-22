"""MaxSAT manifest and output parsing."""

import platform

import pytest

from qecc_sat.maxsat_external import parse_cominisatps_optimal, parse_o_v_lines
from qecc_sat.maxsat_registry import (
    MaxSATNotInstalledError,
    _which_usable,
    get_spec,
    host_supports_linux_elf,
    list_status,
    load_manifest,
    maxsat_runnable_on_host,
    resolve_executable,
)


def test_manifest_loads():
    specs = load_manifest()
    ids = {s.id for s in specs}
    assert "cashw-coreplus" in ids
    assert "evalmaxsat" in ids
    assert "maxcdcl" in ids
    assert "open-wbo" in ids


def test_parse_o_v_lines():
    text = "c comment\no 6\nv 1 -2 3 0\n"
    cost, model = parse_o_v_lines(text)
    assert cost == 6
    assert model == [1, -2, 3]


def test_parse_o_v_lines_compact_binary_model():
    """CASHW's ``-bm`` output encodes assignments as a compact bitstring."""
    cost, model = parse_o_v_lines("c comment\no 2\nv 1010\n")

    assert cost == 2
    assert model == [1, -2, 3, -4]


def test_get_spec_cashw():
    spec = get_spec("cashw-coreplus")
    assert "cashwmaxsatcoreplus" in spec.executable_relpath
    assert spec.linux_elf


def test_get_spec_evalmaxsat():
    spec = get_spec("evalmaxsat")
    assert spec.executable_relpath.endswith("EvalMaxSAT")
    assert spec.output_format == "o_v_lines"


def test_parse_cominisatps_optimal():
    text = "c initCost: 0, fixedBySearch: 0, optimal: 3, maxsat: 2\ns SATISFIABLE\n"
    cost, model = parse_cominisatps_optimal(text)
    assert cost == 3
    assert model is None


def test_linux_elf_not_runnable_off_linux():
    if host_supports_linux_elf():
        pytest.skip("linux host")
    assert not maxsat_runnable_on_host("cashw-coreplus")
    assert not maxsat_runnable_on_host("evalmaxsat")
    row = next(r for r in list_status() if r["id"] == "cashw-coreplus")
    if row["installed"]:
        assert row.get("skipped_host")
        assert row["error"] is None


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Windows chmod does not model POSIX unreadable executable permissions",
)
def test_unreadable_path_shadow_is_ignored(monkeypatch, tmp_path):
    """PATH may contain root-owned stubs; do not treat them as installed."""
    bad = tmp_path / "cashwmaxsatcoreplus"
    bad.write_bytes(b"\x7fELF")
    bad.chmod(0o000)
    try:
        monkeypatch.setattr("qecc_sat.maxsat_registry.shutil.which", lambda _n: str(bad))
        assert _which_usable("cashwmaxsatcoreplus") is None
        rows = list_status()
        assert all(
            not r["runnable"] or "cashw" not in r["id"]
            for r in rows
            if r["path"] == str(bad)
        )
    finally:
        bad.chmod(0o644)


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
