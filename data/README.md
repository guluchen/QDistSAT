# Benchmark matrices

Files use the same layout as [DistQLDPC](https://github.com/guluchen/DistQLDPC):

| Suffix | Role |
|--------|------|
| `_Hx.txt`, `_Hz.txt` | CSS parity checks |
| `_Gx.txt`, `_Gz.txt` | Logical-operator bases (from `precompute-logicals`) |

Each line is a binary row (`0` / `1`, space-separated).

**Stem names** use `{family}_{n}_{k}_{d}` (e.g. `BB_72_12_6`, `LP_34_20_2`).
Use `unknown` when minimum distance is not certified (`BB_288_12_unknown`). This
portable spelling avoids reserved filename characters on Windows. See [NOTICE](../NOTICE)
for upstream IDs (e.g. codeDistancePYPI `AJ_*` / `xu_*` renamed to `LP_*`).

## Copyright and attribution

**Full legal text:** [NOTICE](../NOTICE) at the repository root.

- **LP_*, PK_*, TN_*** stems: derived from
  [codeDistancePYPI](https://github.com/m-webster/codeDistancePYPI) examples (MIT);
  `LP_*` files were renamed from upstream `AJ_*` / `xu_*` (listed in NOTICE).
- **BB_*, TN_*, GB_*, …**: provided under GPL-3.0-or-later together with QDistSAT /
  DistQLDPC (see NOTICE). Some BB/GB stems were renamed to match certified `d`; see NOTICE §2b.

Do not redistribute matrix subsets without retaining the notices above.

## Generate Gx / Gz

```bash
python3 -m venv venv && source venv/bin/activate
python3 -m pip install -e .
precompute-logicals BB_108_8_10
```

Default root: `data/` (`--benchmark-dir` or `--stems-dir`; subdirs `BB`, `LP`, `QT`, …).

## Six experiment batches (`BB`, `BB2`, `QT`, `QT2`, `LP`, `LP2`)

Matrices live under `data/BB`, `data/BB2`, `data/LP`, `data/LP2`, `data/QT`, `data/QT2`.
Use `--stems-dir data` to benchmark all stems in those folders (recursive search).

Run all six in parallel (default 60s per config, all default solvers, one log per folder):

```bash
source venv/bin/activate   # or: export PYTHON=$PWD/venv/bin/python
pip install -e ".[dev]"
./scripts/run_benchmark_six_stemdirs.sh              # -d 20; splits (nproc−4)/6 --jobs per dir
./scripts/run_benchmark_six_stemdirs.sh --jobs-total 120   # ~20 workers × 6 dirs
./scripts/run_benchmark_six_stemdirs.sh -d 20 --timeout 120 --foreground
```
