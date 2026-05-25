#!/usr/bin/env python3
"""
One-shot setup for ``benchmarks/benchmark_solver_performance.py`` default run.

Installs (default = full benchmark stack):
  - Python extras: z3-solver, cvc5 (SMT backends z3py / cvc5)
  - codeDistancePYPI pip extra + dist-m4ri binary (``cd-*`` comparison solvers)
  - External MaxSAT zips + Open-WBO (``download_maxsat_solvers.py --bench``)
  - DistQLDPC reference binary (``bin/distqldpc``)

Use ``--no-comparison`` to skip codedistance / dist-m4ri (large pip deps).

PySAT SAT/RC2 solvers need only ``pip install -e ".[dev]"`` (no download).

Examples:
  python3 scripts/install_benchmark_deps.py
  python3 scripts/install_benchmark_deps.py --list
  python3 scripts/install_benchmark_deps.py --skip-maxsat   # SMT + DistQLDPC only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _codedistance_available() -> bool:
    try:
        from qecc_sat.codedistance_runner import codedistance_available

        return codedistance_available()
    except ImportError:
        return False


def _z3_available() -> bool:
    try:
        import z3  # noqa: F401

        return True
    except ImportError:
        return False


def _cvc5_available() -> bool:
    try:
        import cvc5  # noqa: F401

        return True
    except ImportError:
        return False


def _print_pip_solver_status() -> None:
    for name, ok, pkg in (
        ("z3py", _z3_available(), "z3-solver"),
        ("cvc5", _cvc5_available(), "cvc5"),
        ("codedistance", _codedistance_available(), "codedistance (comparison extra)"),
    ):
        mark = "OK" if ok else "missing"
        print(f"{name:<22} {mark:<10} pip package {pkg}")
        if not ok:
            hint = "pip install -e \".[comparison]\"" if name == "codedistance" else f"pip install {pkg}"
            print(f"  ! {hint}")


def _pip_install_one(spec: str) -> bool:
    """Install one pip package; return False on failure (e.g. z3-solver on new Python)."""
    for attempt in (
        [sys.executable, "-m", "pip", "install", spec],
        [sys.executable, "-m", "pip", "install", "--only-binary", ":all:", spec],
    ):
        print(f"# {' '.join(attempt)}", flush=True)
        try:
            subprocess.check_call(attempt, cwd=REPO_ROOT)
            return True
        except subprocess.CalledProcessError:
            continue
    print(f"# Warning: could not install {spec!r}", flush=True)
    return False


def _run_pip_benchmark_extras(*, dev: bool, comparison: bool) -> None:
    if dev:
        print("# pip install -e .[dev]", flush=True)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-e", ".[dev]"],
            cwd=REPO_ROOT,
        )
    if comparison:
        print("# pip install -e .[comparison]", flush=True)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-e", ".[comparison]"],
            cwd=REPO_ROOT,
        )
    for _name, spec in (("cvc5", "cvc5>=1.2"), ("z3-solver", "z3-solver>=4.12")):
        _pip_install_one(spec)


def _run_dist_m4ri(*, no_install_deps: bool, force: bool) -> None:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "install_dist_m4ri.py")]
    if no_install_deps:
        cmd.append("--no-install-deps")
    if force:
        cmd.append("--force")
    print(f"# {' '.join(cmd)}", flush=True)
    try:
        subprocess.check_call(cmd, cwd=REPO_ROOT)
    except subprocess.CalledProcessError:
        print(
            "# Warning: dist-m4ri install failed (cd-m4ri-cc will stay unavailable)",
            flush=True,
        )


def _run_maxsat_bench(*, no_distqldpc: bool, no_install_deps: bool, force: bool) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "download_maxsat_solvers.py"),
        "--bench",
    ]
    if no_distqldpc:
        cmd.append("--no-distqldpc")
    if no_install_deps:
        cmd.append("--no-install-deps")
    if force:
        cmd.append("--force")
    print(f"# {' '.join(cmd)}", flush=True)
    subprocess.check_call(cmd, cwd=REPO_ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install full benchmark dependencies (SMT, MaxSAT, DistQLDPC, codeDistance)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "After install, run:\n"
            "  python3 benchmarks/benchmark_solver_performance.py --list-solvers\n"
            "  python3 benchmarks/benchmark_solver_performance.py --stem BB_72_12_6"
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Show status (pip SMT packages, MaxSAT, DistQLDPC)",
    )
    parser.add_argument(
        "--skip-pip",
        action="store_true",
        help="Do not pip install z3-solver / cvc5 (benchmark extra)",
    )
    parser.add_argument(
        "--with-dev",
        action="store_true",
        help="Also install pytest via pip install -e '.[dev,benchmark]'",
    )
    parser.add_argument(
        "--no-comparison",
        action="store_true",
        help="Skip pip install -e '.[comparison]' and dist-m4ri (cd-gurobi, cd-mip-scip, cd-m4ri-cc, cd-magma)",
    )
    parser.add_argument(
        "--skip-maxsat",
        action="store_true",
        help="Skip download_maxsat_solvers.py --bench",
    )
    parser.add_argument(
        "--no-distqldpc",
        action="store_true",
        help="Pass --no-distqldpc to download_maxsat_solvers.py",
    )
    parser.add_argument(
        "--no-install-system-deps",
        action="store_true",
        help="Do not let download script run apt/brew for GMP/zlib",
    )
    parser.add_argument("--force", action="store_true", help="Force reinstall MaxSAT/DistQLDPC")
    args = parser.parse_args()

    install_comparison = not args.no_comparison

    if args.list:
        print("# Python SMT + codeDistance", flush=True)
        _print_pip_solver_status()
        print("\n# dist-m4ri (cd-m4ri-cc)", flush=True)
        subprocess.check_call(
            [sys.executable, str(REPO_ROOT / "scripts" / "install_dist_m4ri.py"), "--status"],
            cwd=REPO_ROOT,
        )
        print("\n# External MaxSAT + DistQLDPC", flush=True)
        subprocess.check_call(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "download_maxsat_solvers.py"),
                "--list",
            ],
            cwd=REPO_ROOT,
        )
        return

    if not args.skip_pip:
        _run_pip_benchmark_extras(dev=args.with_dev, comparison=install_comparison)
        print(flush=True)

    if install_comparison:
        _run_dist_m4ri(no_install_deps=args.no_install_system_deps, force=args.force)
        print(flush=True)

    if not args.skip_maxsat:
        _run_maxsat_bench(
            no_distqldpc=args.no_distqldpc,
            no_install_deps=args.no_install_system_deps,
            force=args.force,
        )
        print(flush=True)
    elif not args.no_distqldpc:
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "install_distqldpc.py"),
        ]
        if args.force:
            cmd.append("--force")
        if args.no_install_system_deps:
            cmd.append("--no-install-deps")
        print(f"# {' '.join(cmd)}", flush=True)
        subprocess.check_call(cmd, cwd=REPO_ROOT)
        print(flush=True)

    print("# SMT backends", flush=True)
    _print_pip_solver_status()
    if install_comparison and not _codedistance_available():
        print(
            "# Warning: codedistance pip package still missing — run:",
            flush=True,
        )
        print('  pip install -e ".[comparison]"', flush=True)
    print("\n# External binaries (full list)", flush=True)
    subprocess.check_call(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "download_maxsat_solvers.py"),
            "--list",
        ],
        cwd=REPO_ROOT,
    )


if __name__ == "__main__":
    main()
