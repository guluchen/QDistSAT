# Benchmark matrices

Files use the same layout as [DistQLDPC](https://github.com/guluchen/DistQLDPC):

| Suffix | Role |
|--------|------|
| `_Hx.txt`, `_Hz.txt` | CSS parity checks |
| `_Gx.txt`, `_Gz.txt` | Logical-operator bases (from `precompute-logicals`) |

Each line is a binary row (`0` / `1`, space-separated).

## Copyright and attribution

**Full legal text:** [NOTICE](../NOTICE) at the repository root.

- **AJ_*, PK_*, TN_*, xu_*** stems: derived from
  [codeDistancePYPI](https://github.com/m-webster/codeDistancePYPI) examples (MIT).
- **BB_*, QT_*, GB_*, …**: provided under GPL-3.0-or-later together with QDistSAT /
  DistQLDPC (see NOTICE).

Do not redistribute matrix subsets without retaining the notices above.

## Generate Gx / Gz

```bash
python3 -m venv venv && source venv/bin/activate
python3 -m pip install -e .
precompute-logicals BB_108_8_10
```

Default directory: `data/matrices` (`--benchmark-dir` to override).

## Six experiment batches (`BB`, `BB2`, `QT`, `QT2`, `LP`, `LP2`)

Matrices for batch runs live under `data/BB`, `data/BB2`, … (each folder is a `--stems-dir`).

Run all six in parallel (default 60s per config, all default solvers, one log per folder):

```bash
source venv/bin/activate   # or: export PYTHON=$PWD/venv/bin/python
pip install -e ".[dev]"
./scripts/run_benchmark_six_stemdirs.sh              # -d 20; splits (nproc−4)/6 --jobs per dir
./scripts/run_benchmark_six_stemdirs.sh --jobs-total 120   # ~20 workers × 6 dirs
./scripts/run_benchmark_six_stemdirs.sh -d 20 --timeout 120 --foreground
```
