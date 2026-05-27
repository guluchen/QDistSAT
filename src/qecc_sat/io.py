"""Matrix and logical-basis file I/O shared by CLI and tools."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from .qecc_distance import symplectic_from_css_nbit_rows


def load_logical_basis(path: str) -> list[list[int]]:
    """Load logical basis rows from a text file (0/1 per entry, one row per line)."""
    rows: list[list[int]] = []
    f = sys.stdin if path == "-" else open(path)
    try:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "#" in line:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
            rows.append([int(x) % 2 for x in line.split()])
    finally:
        if path != "-":
            f.close()
    if not rows:
        raise ValueError(f"no data rows in logical basis file {path!r}")
    return rows


def stem_from_parity_hx_path(hx_path: str) -> str:
    """Stem for stem_Hx.txt / stem_Hz.txt / stem_Gx.txt / stem_Gz.txt."""
    b = os.path.basename(hx_path)
    if b.endswith("_Hx.txt"):
        return b[: -len("_Hx.txt")]
    return os.path.splitext(b)[0]


def discover_css_matrix_stems(
    root: Path | str,
    *,
    recursive: bool = True,
) -> list[tuple[str, Path]]:
    """
    Find ``(stem, directory)`` pairs with matching ``{stem}_Hx.txt`` and ``{stem}_Hz.txt``.

    When ``recursive`` is True (default), searches ``root`` and all subdirectories.
    Otherwise only immediate children of ``root``.
    """
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    if recursive:
        hx_paths = sorted(root.rglob("*_Hx.txt"))
    else:
        hx_paths = sorted(root.glob("*_Hx.txt"))

    out: list[tuple[str, Path]] = []
    seen: dict[str, Path] = {}
    for hx in hx_paths:
        stem = stem_from_parity_hx_path(str(hx))
        hz = hx.parent / f"{stem}_Hz.txt"
        if not hz.is_file():
            continue
        if stem in seen:
            raise ValueError(
                f"duplicate stem {stem!r} under {root}: "
                f"{seen[stem]} and {hx.parent}"
            )
        seen[stem] = hx.parent
        out.append((stem, hx.parent))
    return sorted(out, key=lambda t: t[0])


def resolve_matrix_dir_for_stem(root: Path | str, stem: str) -> Path:
    """Directory containing ``{stem}_Hx.txt`` / ``{stem}_Hz.txt`` under ``root``."""
    root = Path(root)
    direct_hx = root / f"{stem}_Hx.txt"
    if direct_hx.is_file() and (root / f"{stem}_Hz.txt").is_file():
        return root
    matches = [
        p
        for p in root.rglob(f"{stem}_Hx.txt")
        if (p.parent / f"{stem}_Hz.txt").is_file()
    ]
    if len(matches) == 1:
        return matches[0].parent
    if len(matches) > 1:
        parents = sorted({p.parent for p in matches})
        raise ValueError(
            f"stem {stem!r} found in multiple directories under {root}: {parents}"
        )
    raise FileNotFoundError(
        f"no {{stem}}_Hx.txt + {{stem}}_Hz.txt under {root} for stem={stem!r}"
    )


def resolve_precomputed_logical_basis(
    hx_path: str,
    n: int,
) -> tuple[Optional[list[list[int]]], Optional[str], Optional[str]]:
    """
    Returns ``(symplectic_rows, description, precompute_error)``.

    Loads ``stem_Gx.txt`` + ``stem_Gz.txt`` next to ``hx_path``. Third component is ``None`` on success;
    otherwise ``\"missing\"`` or ``\"incomplete\"``.
    """
    d = os.path.dirname(hx_path) or "."
    stem = stem_from_parity_hx_path(hx_path)
    base = os.path.join(d, stem)
    gx_path = base + "_Gx.txt"
    gz_path = base + "_Gz.txt"
    has_gx = os.path.isfile(gx_path)
    has_gz = os.path.isfile(gz_path)
    if has_gx and has_gz:
        z_rows = load_logical_basis(gx_path)
        x_rows = load_logical_basis(gz_path)
        for i, row in enumerate(z_rows):
            if len(row) != n:
                raise ValueError(
                    f"{gx_path} row {i}: length {len(row)} != n={n} (Z-type logical rows)"
                )
        for i, row in enumerate(x_rows):
            if len(row) != n:
                raise ValueError(
                    f"{gz_path} row {i}: length {len(row)} != n={n} (X-type logical rows)"
                )
        sym = symplectic_from_css_nbit_rows(z_rows, x_rows, n)
        return sym, f"{gx_path} + {gz_path}", None
    if has_gx ^ has_gz:
        return None, None, "incomplete"
    return None, None, "missing"


def load_matrix(path: str) -> list[list[int]]:
    """Load matrix from file (or stdin if path is '-'): space-separated 0/1, one row per line."""
    rows: list[list[int]] = []
    f = sys.stdin if path == "-" else open(path)
    try:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = [int(x) % 2 for x in line.split()]
            rows.append(row)
    finally:
        if path != "-":
            f.close()
    return rows


def build_s_from_hx_hz(Hx: list[list[int]], Hz: list[list[int]]) -> list[list[int]]:
    """Build symplectic stabilizer matrix S from CSS parity checks. S = [Hx|0] ∥ [0|Hz]."""
    n = len(Hx[0]) if Hx else len(Hz[0]) if Hz else 0
    if n == 0:
        return []
    s: list[list[int]] = []
    for row in Hx:
        s.append(row + [0] * n)
    for row in Hz:
        s.append([0] * n + row)
    return s
