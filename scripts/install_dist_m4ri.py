#!/usr/bin/env python3
"""
Clone and build dist-m4ri (https://github.com/QEC-pages/dist-m4ri) for codeDistance ``dist_m4ri_CC``.

Install layout:
  vendor/dist-m4ri/     git clone; built in src/
  bin/dist_m4ri         symlink → vendor/dist-m4ri/src/dist_m4ri

Requires libm4ri (Ubuntu: libm4ri-dev; macOS: brew install m4ri).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = REPO_ROOT / "vendor" / "dist-m4ri"
SRC_DIR = VENDOR_DIR / "src"
BUILT_EXE = SRC_DIR / "dist_m4ri"
PUBLIC_BIN = REPO_ROOT / "bin" / "dist_m4ri"
DIST_M4RI_GIT = "https://github.com/QEC-pages/dist-m4ri.git"


def _brew_m4ri_flags() -> tuple[str, str]:
    brew = shutil.which("brew")
    if not brew:
        return "", ""
    try:
        prefix = subprocess.check_output(
            [brew, "--prefix", "m4ri"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return "", ""
    if not prefix or not Path(prefix).is_dir():
        return "", ""
    return f"-I{prefix}/include", f"-L{prefix}/lib"


def _have_m4ri_headers() -> bool:
    candidates = [
        "/usr/include/m4ri/m4ri.h",
        "/usr/local/include/m4ri/m4ri.h",
    ]
    inc, _ = _brew_m4ri_flags()
    if inc.startswith("-I"):
        candidates.append(f"{inc[2:]}/m4ri/m4ri.h")
    return any(Path(p).is_file() for p in candidates)


def _m4ri_compile_flags() -> tuple[str, str]:
    """(CFLAGS suffix, link -L flags) for make; dist-m4ri makefile ignores env CFLAGS."""
    inc, lib = _brew_m4ri_flags()
    if not inc and Path("/usr/include/m4ri/m4ri.h").is_file():
        return "", ""
    if sys.platform == "darwin":
        opt = "-g -mtune=native -O3"
    else:
        opt = "-g -march=native -mtune=native -O3"
    warn = "-Wall -Wsign-compare -Wextra -DNDEBUG"
    cflags = f"{opt} {warn}"
    if inc:
        cflags = f"{cflags} {inc}"
    return cflags, lib


def _make_env() -> dict[str, str]:
    env = os.environ.copy()
    _, lib = _brew_m4ri_flags()
    brew = shutil.which("brew")
    if brew:
        try:
            prefix = subprocess.check_output(
                [brew, "--prefix", "m4ri"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            prefix = ""
        if prefix:
            inc_dir = f"{prefix}/include"
            lib_dir = f"{prefix}/lib"
            env["CPATH"] = os.pathsep.join(
                x for x in (inc_dir, env.get("CPATH", "")) if x
            )
            env["LIBRARY_PATH"] = os.pathsep.join(
                x for x in (lib_dir, env.get("LIBRARY_PATH", "")) if x
            )
    if lib:
        env["LDFLAGS"] = " ".join(x for x in (env.get("LDFLAGS", ""), lib) if x).strip()
    return env


def _make_target() -> list[str]:
    """make argv for dist_m4ri (macOS often needs OPT without -march=native)."""
    cflags, lib = _m4ri_compile_flags()
    cmd = ["make", "-C", str(SRC_DIR), "dist_m4ri", f"CFLAGS={cflags}"]
    if lib:
        # Link recipe is: ... -lm4ri -lm — prepend -L from Homebrew/apt.
        cmd.append(f"LDLIBS={lib} -lm4ri -lm")
    if sys.platform != "darwin":
        cmd.insert(3, "-j")
    return cmd


def _try_install_build_deps() -> bool:
    if shutil.which("gcc") and shutil.which("make") and _have_m4ri_headers():
        return True
    print("# dist-m4ri build deps missing; installing (gcc, make, libm4ri)…", flush=True)
    try:
        if Path("/etc/debian_version").is_file() and shutil.which("apt-get"):
            subprocess.check_call(
                ["sudo", "apt-get", "install", "-y", "gcc", "make", "libm4ri-dev"],
            )
        elif sys.platform == "darwin" and shutil.which("brew"):
            subprocess.check_call(["brew", "install", "m4ri"])
        else:
            return False
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"# Auto-install failed: {exc}", flush=True)
        return False
    return bool(shutil.which("gcc") and shutil.which("make") and _have_m4ri_headers())


def _build_deps_hint() -> str:
    if Path("/etc/debian_version").is_file():
        pkg = "sudo apt install -y gcc make libm4ri-dev"
    elif sys.platform == "darwin":
        pkg = "brew install m4ri   # then: python3 scripts/install_dist_m4ri.py"
    else:
        pkg = "install gcc, make, and libm4ri development headers"
    return (
        "dist-m4ri build requires gcc, make, and libm4ri.\n\n"
        f"  {pkg}\n\n"
        "Then re-run: python3 scripts/install_dist_m4ri.py"
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
        err = f"broken symlink {PUBLIC_BIN} (run: python3 scripts/install_dist_m4ri.py)"
    elif not installed:
        err = "not installed (run: python3 scripts/install_dist_m4ri.py)"
    else:
        err = None
    return {
        "id": "dist_m4ri",
        "title": "dist-m4ri binary (codeDistance dist_m4ri_CC)",
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
    if not shutil.which("gcc") or not shutil.which("make"):
        raise SystemExit(_build_deps_hint())
    if not _have_m4ri_headers():
        raise SystemExit(_build_deps_hint())

    if force and VENDOR_DIR.is_dir():
        print(f"# Removing {VENDOR_DIR}", flush=True)
        shutil.rmtree(VENDOR_DIR)

    if is_installed() and not force:
        print(f"# Already OK: dist-m4ri ({BUILT_EXE})", flush=True)
        _link_public_bin()
        return

    VENDOR_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not (VENDOR_DIR / ".git").is_dir():
        print(f"# Cloning {DIST_M4RI_GIT}", flush=True)
        subprocess.check_call(
            ["git", "clone", "--depth", "1", DIST_M4RI_GIT, str(VENDOR_DIR)],
        )
    print(f"# Building dist-m4ri ({' '.join(_make_target())})", flush=True)
    subprocess.check_call(_make_target(), env=_make_env())
    if not is_installed():
        raise SystemExit(f"Build did not produce {BUILT_EXE}")
    _link_public_bin()
    print(f"# OK: {BUILT_EXE}", flush=True)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Install dist-m4ri under vendor/dist-m4ri for cd-m4ri-cc benchmarks",
    )
    parser.add_argument("--force", action="store_true", help="Re-clone and rebuild")
    parser.add_argument(
        "--no-install-deps",
        action="store_true",
        help="Do not run apt/brew for gcc/libm4ri",
    )
    parser.add_argument("--status", action="store_true", help="Print install status")
    args = parser.parse_args()
    if args.status:
        print_status()
        return
    install(force=args.force, auto_install_deps=not args.no_install_deps)


if __name__ == "__main__":
    main()
