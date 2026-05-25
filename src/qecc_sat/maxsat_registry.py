"""
Registry and path resolution for external MaxSAT binaries (``bin/maxsat/``).
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import REPO_ROOT

MANIFEST_PATH = REPO_ROOT / "bin" / "maxsat" / "manifest.json"


class MaxSATPlatformError(RuntimeError):
    """External MaxSAT binary exists but cannot run on this OS/architecture."""


class MaxSATNotInstalledError(FileNotFoundError):
    """External MaxSAT binary missing under ``bin/maxsat/``."""


DEFAULT_MAXSAT_DIR = REPO_ROOT / "bin" / "maxsat"


@dataclass(frozen=True)
class MaxSATBinarySpec:
    """One external MaxSAT executable described in ``manifest.json``."""

    id: str
    solver_type: str
    title: str
    executable_relpath: str
    command: Sequence[str]
    output_format: str
    linux_elf: bool = False
    zip_url: Optional[str] = None
    zip_root: Optional[str] = None
    git_url: Optional[str] = None
    git_ref: Optional[str] = None
    build: Optional[str] = None
    install_layout: str = "subdir"

    def install_dir(self, root: Optional[Path] = None) -> Path:
        return maxsat_root(root) / self.id

    def executable_path(self, root: Optional[Path] = None) -> Path:
        if self.install_layout == "flat":
            return maxsat_root(root) / self.executable_relpath
        return self.install_dir(root) / self.executable_relpath


def maxsat_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("QEECC_SAT_MAXSAT_DIR")
    if env:
        return Path(env)
    return DEFAULT_MAXSAT_DIR


def host_supports_linux_elf() -> bool:
    """True on Linux x86_64 (MSE prebuilt ELF targets)."""
    if platform.system() != "Linux":
        return False
    return platform.machine().lower() in ("x86_64", "amd64")


def load_manifest(path: Optional[Path] = None) -> List[MaxSATBinarySpec]:
    p = path or MANIFEST_PATH
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    out: List[MaxSATBinarySpec] = []
    for row in data.get("solvers", []):
        out.append(
            MaxSATBinarySpec(
                id=str(row["id"]),
                solver_type=str(row["solver_type"]),
                title=str(row.get("title", row["id"])),
                executable_relpath=str(row["executable_relpath"]),
                command=tuple(str(x) for x in row["command"]),
                output_format=str(row.get("output_format", "o_v_lines")),
                linux_elf=bool(row.get("linux_elf", False)),
                zip_url=row.get("zip_url"),
                zip_root=row.get("zip_root"),
                git_url=row.get("git_url"),
                git_ref=row.get("git_ref"),
                build=row.get("build"),
                install_layout=str(row.get("install_layout", "subdir")),
            )
        )
    return out


def manifest_by_solver_type(
    path: Optional[Path] = None,
) -> Dict[str, MaxSATBinarySpec]:
    return {s.solver_type: s for s in load_manifest(path)}


def get_spec(solver_type: str, path: Optional[Path] = None) -> MaxSATBinarySpec:
    table = manifest_by_solver_type(path)
    try:
        return table[solver_type]
    except KeyError:
        known = ", ".join(sorted(table))
        raise KeyError(
            f"Unknown external MaxSAT solver {solver_type!r}. Known: {known}"
        ) from None


def _read_magic(path: Path, n: int = 4) -> bytes:
    with open(path, "rb") as f:
        return f.read(n)


def platform_mismatch_message(exe: Path) -> Optional[str]:
    """Non-None if an MSE Linux ELF binary cannot run on this host."""
    if not exe.is_file():
        return None
    if not _read_magic(exe, 4).startswith(b"\x7fELF"):
        return None
    if host_supports_linux_elf():
        return None
    return "unsupported platform"


def not_installed_status(spec: MaxSATBinarySpec) -> str:
    if spec.id == "open-wbo":
        return "not installed (run: python3 scripts/download_maxsat_solvers.py --bench)"
    if spec.zip_url and spec.linux_elf:
        return "not installed (run: python3 scripts/download_maxsat_solvers.py --bench)"
    if spec.zip_url is None and spec.git_url is None:
        return f"not installed (place binary at {spec.executable_path()})"
    return f"not installed (run: python3 scripts/download_maxsat_solvers.py --only {spec.id})"


def assert_runnable(exe: Path) -> None:
    msg = platform_mismatch_message(exe)
    if msg:
        raise MaxSATPlatformError(msg)


def resolve_executable(
    solver_type: str,
    *,
    root: Optional[Path] = None,
    path: Optional[Path] = None,
    check_platform: bool = False,
) -> Path:
    """
    Return path to the binary if installed; raise ``FileNotFoundError`` otherwise.
    """
    spec = get_spec(solver_type, path=path)
    exe = spec.executable_path(root)
    if exe.is_file():
        if check_platform:
            assert_runnable(exe)
        return exe
    which = shutil.which(exe.name)
    if which:
        p = Path(which)
        if check_platform:
            assert_runnable(p)
        return p
    raise MaxSATNotInstalledError(not_installed_status(spec))


def maxsat_runnable_on_host(solver_type: str, *, root: Optional[Path] = None) -> bool:
    """
    False when an MSE ``linux_elf`` solver is used off Linux, or the binary is missing.
    """
    spec = get_spec(solver_type)
    if spec.linux_elf and not host_supports_linux_elf():
        return False
    try:
        resolve_executable(solver_type, root=root, check_platform=True)
        return True
    except (FileNotFoundError, MaxSATNotInstalledError, MaxSATPlatformError):
        return False


def external_maxsat_skip_reason(solver_type: str, *, root: Optional[Path] = None) -> str:
    """Human-readable reason when ``maxsat_runnable_on_host`` is false."""
    spec = get_spec(solver_type)
    if spec.linux_elf and not host_supports_linux_elf():
        mach = platform.machine()
        return (
            f"MSE linux_elf binary needs Linux x86_64 (this host: "
            f"{platform.system()} {mach})"
        )
    if not is_installed(solver_type, root=root):
        return not_installed_status(spec)
    try:
        resolve_executable(solver_type, root=root, check_platform=True)
    except MaxSATPlatformError as e:
        return str(e)
    except (FileNotFoundError, MaxSATNotInstalledError) as e:
        return str(e)
    return "not runnable (see --list-solvers)"


def is_installed(solver_type: str, *, root: Optional[Path] = None) -> bool:
    try:
        resolve_executable(solver_type, root=root)
        return True
    except (FileNotFoundError, MaxSATNotInstalledError):
        return False


def is_runnable(solver_type: str, *, root: Optional[Path] = None) -> bool:
    return maxsat_runnable_on_host(solver_type, root=root)


def list_status(root: Optional[Path] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for spec in load_manifest():
        exe = spec.executable_path(root)
        installed = exe.is_file() or bool(shutil.which(Path(exe).name))
        skipped_host = spec.linux_elf and not host_supports_linux_elf()
        runnable = False
        err: Optional[str] = None
        if skipped_host:
            pass
        elif installed:
            try:
                resolve_executable(spec.solver_type, root=root, check_platform=True)
                runnable = True
            except MaxSATPlatformError:
                pass
            except (FileNotFoundError, MaxSATNotInstalledError) as e:
                err = str(e)
        else:
            err = not_installed_status(spec)
        path = str(exe)
        if installed and not skipped_host:
            try:
                path = str(resolve_executable(spec.solver_type, root=root))
            except (FileNotFoundError, MaxSATNotInstalledError):
                pass
        rows.append(
            {
                "id": spec.id,
                "solver_type": spec.solver_type,
                "title": spec.title,
                "linux_elf": spec.linux_elf,
                "skipped_host": skipped_host,
                "installed": installed,
                "runnable": runnable,
                "path": path,
                "zip_url": spec.zip_url,
                "error": err,
            }
        )
    return rows


def ensure_executable(path: Path) -> None:
    if platform.system() != "Windows" and path.is_file():
        mode = path.stat().st_mode
        if not (mode & stat.S_IXUSR):
            path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
