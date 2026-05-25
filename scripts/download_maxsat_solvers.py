#!/usr/bin/env python3
"""
Download / build MaxSAT binaries into bin/maxsat/<id>/ (see bin/maxsat/manifest.json).

Examples:
  python3 scripts/download_maxsat_solvers.py --bench   # recommended: maxcdcl + evalmaxsat
  python3 scripts/download_maxsat_solvers.py --list    # check what is installed
  python3 scripts/download_maxsat_solvers.py             # all MSE zip solvers
  python3 scripts/download_maxsat_solvers.py --build open-wbo
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from qecc_sat.maxsat_registry import (  # noqa: E402
    MaxSATBinarySpec,
    ensure_executable,
    host_supports_linux_elf,
    list_status,
    load_manifest,
    maxsat_runnable_on_host,
    maxsat_root,
)

# Matches README quick-start benchmark (--solvers rc2-glucose42 maxcdcl …).
BENCH_ZIP_IDS = ("maxcdcl", "evalmaxsat")


def _download_zip(spec: MaxSATBinarySpec, install_dir: Path) -> None:
    if not spec.zip_url:
        raise SystemExit(f"Solver {spec.id!r} has no zip_url (use --build).")
    install_dir.mkdir(parents=True, exist_ok=True)
    zip_path = install_dir / "_download.zip"
    print(f"# Downloading {spec.title}", flush=True)
    print(f"  {spec.zip_url}", flush=True)
    urlretrieve(spec.zip_url, zip_path)
    print(f"# Extracting -> {install_dir}", flush=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(install_dir)
    zip_path.unlink(missing_ok=True)
    exe = spec.executable_path(install_dir.parent)
    # executable_path uses root/spec.id/... but we pass install_dir = root/spec.id
    exe = install_dir / spec.executable_relpath
    if not exe.is_file():
        raise SystemExit(f"Executable not found after extract: {exe}")
    ensure_executable(exe)
    print(f"# OK: {exe}", flush=True)


def _brew_gmp_flags() -> tuple[str, str]:
    """Return (CFLAGS/LDFLAGS include, libpath) for Homebrew GMP, or empty strings."""
    brew = shutil.which("brew")
    if not brew:
        return "", ""
    try:
        prefix = subprocess.check_output(
            [brew, "--prefix", "gmp"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "", ""
    if not prefix or not Path(prefix).is_dir():
        return "", ""
    return f"-I{prefix}/include", f"-L{prefix}/lib"


def _have_system_gmpxx() -> bool:
    """True if gmpxx.h is at a standard system include path (Linux apt/yum install)."""
    for p in ("/usr/include/gmpxx.h", "/usr/local/include/gmpxx.h"):
        if Path(p).is_file():
            return True
    return False


def _open_wbo_build_env(src: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PWD"] = str(src.resolve())
    inc, lib = _brew_gmp_flags()
    if not inc and not _have_system_gmpxx():
        raise SystemExit(
            "Open-WBO requires GMP (gmpxx.h). On macOS: brew install gmp\n"
            "On Debian/Ubuntu: sudo apt install libgmp-dev"
        )
    if inc:
        for key in ("CFLAGS", "CXXFLAGS", "LDFLAGS", "LFLAGS"):
            env[key] = " ".join(x for x in (env.get(key, ""), inc, lib) if x).strip()
    return env


def _build_git(spec: MaxSATBinarySpec, install_dir: Path) -> None:
    if not spec.git_url:
        raise SystemExit(f"Solver {spec.id!r} has no git_url.")
    install_dir.mkdir(parents=True, exist_ok=True)
    src = install_dir / "src"
    if src.is_dir():
        shutil.rmtree(src)
    print(f"# Cloning {spec.git_url}", flush=True)
    subprocess.check_call(
        ["git", "clone", "--depth", "1", spec.git_url, str(src)],
        cwd=install_dir,
    )
    if spec.git_ref and spec.git_ref not in ("master", "main"):
        subprocess.check_call(["git", "checkout", spec.git_ref], cwd=src)
    build_cmd = (spec.build or "make r").split()
    if spec.id == "open-wbo" and sys.platform == "darwin" and build_cmd == ["make", "rs"]:
        build_cmd = ["make", "r"]  # static link (rs) fails on macOS ld
    print(f"# Building: {' '.join(build_cmd)}", flush=True)
    if spec.id == "open-wbo":
        env = _open_wbo_build_env(src)
    else:
        env = os.environ.copy()
        env["PWD"] = str(src.resolve())
    subprocess.check_call(build_cmd, cwd=src, env=env)
    built = src / spec.executable_relpath
    if not built.is_file():
        for alt in ("open-wbo_release", "open-wbo", "open-wbo_static"):
            cand = src / alt
            if cand.is_file():
                built = cand
                break
    if not built.is_file():
        raise SystemExit(f"Build did not produce {spec.executable_relpath} under {src}")
    install_exe = install_dir / "open-wbo"
    shutil.copy2(built, install_exe)
    ensure_executable(install_exe)
    print(f"# OK: {install_exe}", flush=True)


def _print_status(root: Path) -> None:
    for row in list_status(root):
        if row["runnable"]:
            mark = "OK"
        elif row.get("skipped_host"):
            mark = "skip"
        elif row["installed"]:
            mark = "installed"
        else:
            mark = "missing"
        print(f"{row['id']:<22} {mark:<10} {row['solver_type']}")
        print(f"  {row['title']}")
        print(f"  {row['path']}")
        if row.get("error") and not row["runnable"] and not row.get("skipped_host"):
            print(f"  ! {row['error']}")
    if not host_supports_linux_elf():
        print(
            "# MSE zip solvers (linux_elf) install on any host but run only on Linux x86_64.",
            flush=True,
        )


def _print_post_install_hints(root: Path) -> None:
    runnable = [r["id"] for r in list_status(root) if r["runnable"]]
    if runnable:
        print(f"# Runnable: {', '.join(runnable)}", flush=True)
    print("# Status: python3 scripts/download_maxsat_solvers.py --list", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install external MaxSAT binaries under bin/maxsat/",
        epilog=(
            "Quick path (Linux x86_64): python3 scripts/download_maxsat_solvers.py --bench\n"
            "PySAT solvers (rc2-glucose42, …) need no download."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--bench",
        action="store_true",
        help=f"Install benchmark defaults: {', '.join(BENCH_ZIP_IDS)} (skip if already OK)",
    )
    parser.add_argument("--only", nargs="*", metavar="ID", help="Manifest ids (zip download)")
    parser.add_argument("--build", nargs="*", metavar="ID", help="Build from git")
    parser.add_argument("--list", action="store_true", help="Show install status")
    parser.add_argument("--force", action="store_true", help="Remove install dir first")
    parser.add_argument("--dest", type=Path, default=None, help="Override maxsat root")
    args = parser.parse_args()
    root = maxsat_root(args.dest)

    if args.list:
        _print_status(root)
        return

    if args.bench and args.only:
        raise SystemExit("Use either --bench or --only, not both.")

    specs = {s.id: s for s in load_manifest()}
    to_zip = args.only
    if args.bench:
        to_zip = list(BENCH_ZIP_IDS)
    elif to_zip is None and not args.build:
        # MSE prebuilt zips (CASHW, EvalMaxSAT, MaxCDCL, …)
        to_zip = [s.id for s in specs.values() if s.zip_url and s.linux_elf]

    if to_zip and not host_supports_linux_elf():
        print(
            "# Skipping MSE zip download: need Linux x86_64 to run these binaries.",
            flush=True,
        )
        print("# PySAT solvers (rc2-glucose42, …) still work without external MaxSAT.", flush=True)
        to_zip = []

    for sid in to_zip or []:
        if sid not in specs:
            raise SystemExit(f"Unknown id {sid!r}")
        spec = specs[sid]
        if maxsat_runnable_on_host(spec.solver_type, root=root) and not args.force:
            print(f"# Already OK: {spec.id} ({spec.executable_path(root)})", flush=True)
            continue
        install_dir = root / spec.id
        if install_dir.exists() and args.force:
            shutil.rmtree(install_dir)
        _download_zip(spec, install_dir)

    if to_zip or args.build:
        _print_post_install_hints(root)

    for sid in args.build or []:
        if sid not in specs:
            raise SystemExit(f"Unknown id {sid!r}")
        spec = specs[sid]
        install_dir = root / spec.id
        if install_dir.exists() and args.force:
            shutil.rmtree(install_dir)
        _build_git(spec, install_dir)


if __name__ == "__main__":
    main()
