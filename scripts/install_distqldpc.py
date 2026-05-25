#!/usr/bin/env python3
"""
Clone and build DistQLDPC (https://github.com/guluchen/DistQLDPC).

Install layout:
  vendor/DistQLDPC/     git clone + make
  bin/distqldpc         symlink → vendor/DistQLDPC/bin/distqldpc
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "vendor" / "DistQLDPC"
BUILT_EXE = VENDOR_DIR / "bin" / "distqldpc"
PUBLIC_BIN = REPO_ROOT / "bin" / "distqldpc"
DISTQLDPC_GIT = "https://github.com/guluchen/DistQLDPC.git"


def _brew_zlib_flags() -> tuple[str, str]:
    brew = shutil.which("brew")
    if not brew:
        return "", ""
    try:
        prefix = subprocess.check_output(
            [brew, "--prefix", "zlib"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "", ""
    if not prefix or not Path(prefix).is_dir():
        return "", ""
    return f"-I{prefix}/include", f"-L{prefix}/lib"


def _have_zlib_headers() -> bool:
    candidates = ["/usr/include/zlib.h", "/usr/local/include/zlib.h"]
    inc, _ = _brew_zlib_flags()
    if inc.startswith("-I"):
        candidates.append(f"{inc[2:]}/zlib.h")
    return any(Path(p).is_file() for p in candidates)


def _make_env() -> dict[str, str]:
    env = os.environ.copy()
    inc, lib = _brew_zlib_flags()
    if inc:
        for key in ("CFLAGS", "CXXFLAGS", "LDFLAGS"):
            env[key] = " ".join(x for x in (env.get(key, ""), inc, lib) if x).strip()
    return env


def _try_install_build_deps() -> bool:
    if shutil.which("g++") and shutil.which("make") and _have_zlib_headers():
        return True
    print("# DistQLDPC build deps missing; installing (g++, make, zlib)…", flush=True)
    try:
        if Path("/etc/debian_version").is_file() and shutil.which("apt-get"):
            subprocess.check_call(
                ["sudo", "apt-get", "install", "-y", "g++", "make", "zlib1g-dev"],
            )
        elif sys.platform == "darwin" and shutil.which("brew"):
            subprocess.check_call(["brew", "install", "zlib"])
        else:
            return False
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"# Auto-install failed: {exc}", flush=True)
        return False
    return bool(shutil.which("g++") and shutil.which("make") and _have_zlib_headers())


def _build_deps_hint() -> str:
    if Path("/etc/debian_version").is_file():
        pkg = "sudo apt install -y g++ make zlib1g-dev"
    elif sys.platform == "darwin":
        pkg = "xcode-select --install; brew install zlib  # then: export LDFLAGS=-L$(brew --prefix zlib)/lib"
    else:
        pkg = "install g++, make, and zlib development headers"
    return (
        "DistQLDPC build requires g++, make, and zlib.\n\n"
        f"  {pkg}\n\n"
        "Then re-run: python3 scripts/install_distqldpc.py"
    )


def is_installed() -> bool:
    if BUILT_EXE.is_file() and os.access(BUILT_EXE, os.X_OK):
        return True
    if PUBLIC_BIN.is_symlink() and not PUBLIC_BIN.exists():
        return False
    return PUBLIC_BIN.is_file() and os.access(PUBLIC_BIN, os.X_OK)


def _link_public_bin() -> None:
    PUBLIC_BIN.parent.mkdir(parents=True, exist_ok=True)
    if PUBLIC_BIN.exists() or PUBLIC_BIN.is_symlink():
        PUBLIC_BIN.unlink()
    rel = os.path.relpath(BUILT_EXE, PUBLIC_BIN.parent)
    PUBLIC_BIN.symlink_to(rel)
    print(f"# Linked: {PUBLIC_BIN} -> {rel}", flush=True)


def status() -> Dict[str, Any]:
    installed = is_installed()
    path = str(PUBLIC_BIN if PUBLIC_BIN.exists() else BUILT_EXE)
    if not installed and PUBLIC_BIN.is_symlink() and not PUBLIC_BIN.exists():
        err = f"broken symlink {PUBLIC_BIN} (run: python3 scripts/install_distqldpc.py)"
    elif not installed:
        err = "not installed (run: python3 scripts/install_distqldpc.py)"
    else:
        err = None
    return {
        "id": "distqldpc",
        "title": "DistQLDPC reference distance tool",
        "installed": installed,
        "runnable": installed,
        "path": path,
        "error": err,
    }


def print_status() -> None:
    row = status()
    mark = "OK" if row["runnable"] else "missing"
    print(f"{row['id']:<22} {mark:<10}", flush=True)
    print(f"  {row['title']}", flush=True)
    print(f"  {row['path']}", flush=True)
    if row.get("error") and not row["runnable"]:
        print(f"  ! {row['error']}", flush=True)


def install(*, force: bool = False, auto_install_deps: bool = True) -> None:
    if auto_install_deps and not _try_install_build_deps():
        raise SystemExit(_build_deps_hint())
    if not shutil.which("g++") or not shutil.which("make"):
        raise SystemExit(_build_deps_hint())

    if force and VENDOR_DIR.is_dir():
        print(f"# Removing {VENDOR_DIR}", flush=True)
        shutil.rmtree(VENDOR_DIR)

    if is_installed() and not force:
        print(f"# Already OK: DistQLDPC ({BUILT_EXE})", flush=True)
        _link_public_bin()
        return

    VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not (VENDOR_DIR / ".git").is_dir():
        print(f"# Cloning {DISTQLDPC_GIT}", flush=True)
        subprocess.check_call(
            ["git", "clone", "--depth", "1", DISTQLDPC_GIT, str(VENDOR_DIR)],
        )
    print(f"# Building DistQLDPC (make -C {VENDOR_DIR})", flush=True)
    subprocess.check_call(["make", "-C", str(VENDOR_DIR)], env=_make_env())
    if not is_installed():
        raise SystemExit(f"Build did not produce {BUILT_EXE}")
    _link_public_bin()
    print(f"# OK: {BUILT_EXE}", flush=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Install DistQLDPC under vendor/DistQLDPC")
    parser.add_argument("--force", action="store_true", help="Re-clone and rebuild")
    parser.add_argument(
        "--no-install-deps",
        action="store_true",
        help="Do not run apt/brew for g++/zlib",
    )
    parser.add_argument("--status", action="store_true", help="Print install status")
    args = parser.parse_args()
    if args.status:
        print_status()
        return
    install(force=args.force, auto_install_deps=not args.no_install_deps)


if __name__ == "__main__":
    main()
