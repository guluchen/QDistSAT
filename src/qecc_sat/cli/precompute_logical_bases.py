#!/usr/bin/env python3
"""
Precompute CSS logical operators and write stem_Gx.txt + stem_Gz.txt.

Reads parity checks **stem_Hx.txt** and **stem_Hz.txt**. Writes:

  - **stem_Gx.txt** — Z-type logical reps in ``F_2^n`` (rows of ``ker(Hx)/row(Hz)``)
  - **stem_Gz.txt** — X-type logical reps (rows of ``ker(Hz)/row(Hx)``)

Usage:
  python precompute_logical_bases.py [STEM] [--benchmark-dir DIR]

If STEM is omitted, every ``*_Hx.txt`` in DIR is processed. If STEM is given, only that code.
"""

from __future__ import annotations

import argparse
import os
import sys

from qecc_sat import DEFAULT_MATRIX_DIR
from qecc_sat.io import discover_css_matrix_stems, load_matrix
from qecc_sat.qecc_distance import css_logical_nbit_rows


def _stem_from_hx_path(hx_path: str) -> str:
    b = os.path.basename(hx_path)
    if b.endswith("_Hx.txt"):
        return b[: -len("_Hx.txt")]
    return os.path.splitext(b)[0]


def precompute_one(hx_path: str, hz_path: str, *, overwrite: bool) -> bool:
    Hx = load_matrix(hx_path)
    Hz = load_matrix(hz_path)
    if not Hx or not Hz:
        print(f"# skip (empty): {hx_path}", file=sys.stderr)
        return False
    n = len(Hx[0])
    if len(Hz[0]) != n:
        print(f"# skip (n mismatch): {hx_path}", file=sys.stderr)
        return False
    bz, bx = css_logical_nbit_rows(Hx, Hz)
    if not bz and not bx:
        print(f"# skip (no logicals): {hx_path}", file=sys.stderr)
        return False

    d = os.path.dirname(hx_path) or "."
    stem = _stem_from_hx_path(hx_path)
    out_gx = os.path.join(d, stem + "_Gx.txt")
    out_gz = os.path.join(d, stem + "_Gz.txt")

    for p in (out_gx, out_gz):
        if os.path.exists(p) and not overwrite:
            print(f"# skip (exists): {p}", file=sys.stderr)
            return False

    if d:
        os.makedirs(d, exist_ok=True)

    with open(out_gx, "w", encoding="utf-8") as f:
        f.write(
            f"# n={n}  Z-type logical rows  ker(Hx)/row(Hz)  parity {os.path.basename(hx_path)}\n"
        )
        for row in bz:
            f.write(" ".join(str(int(x) % 2) for x in row) + "\n")

    with open(out_gz, "w", encoding="utf-8") as f:
        f.write(
            f"# n={n}  X-type logical rows  ker(Hz)/row(Hx)  parity {os.path.basename(hz_path)}\n"
        )
        for row in bx:
            f.write(" ".join(str(int(x) % 2) for x in row) + "\n")

    print(
        f"Wrote {out_gx} ({len(bz)} rows), {out_gz} ({len(bx)} rows)",
        flush=True,
    )
    return True


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Write {STEM}_Gx.txt / {STEM}_Gz.txt from {STEM}_Hx.txt / {STEM}_Hz.txt"
    )
    ap.add_argument(
        "stem",
        nargs="?",
        default=None,
        metavar="STEM",
        help="Benchmark name only (e.g. BB_144_14_14); omit to process all *_Hx.txt in --benchmark-dir",
    )
    ap.add_argument(
        "--benchmark-dir",
        default=str(DEFAULT_MATRIX_DIR),
        metavar="DIR",
        help="Root directory for matrices (default: data/; recurses into subdirs)",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing stem_Gx.txt / stem_Gz.txt",
    )
    args = ap.parse_args()
    d = os.path.normpath(args.benchmark_dir)

    if args.stem is not None:
        from qecc_sat.io import resolve_matrix_dir_for_stem

        try:
            stem_dir = resolve_matrix_dir_for_stem(d, args.stem)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        hx_path = os.path.join(stem_dir, f"{args.stem}_Hx.txt")
        hz_path = os.path.join(stem_dir, f"{args.stem}_Hz.txt")
        ok = precompute_one(hx_path, hz_path, overwrite=args.overwrite)
        print("Done: 1 code written." if ok else "Done: skipped or failed (see above).", flush=True)
        return

    try:
        stem_dirs = discover_css_matrix_stems(d, recursive=True)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if not stem_dirs:
        print(f"No *_Hx.txt + *_Hz.txt pairs under {d!r}", file=sys.stderr)
        sys.exit(1)
    ok = 0
    for stem, stem_dir in stem_dirs:
        hx_path = os.path.join(stem_dir, f"{stem}_Hx.txt")
        hz_path = os.path.join(stem_dir, f"{stem}_Hz.txt")
        if not os.path.isfile(hz_path):
            print(f"# skip (no Hz): {hz_path}", file=sys.stderr)
            continue
        if precompute_one(hx_path, hz_path, overwrite=args.overwrite):
            ok += 1
    print(f"Done: {ok} code(s) written.", flush=True)


if __name__ == "__main__":
    main()
