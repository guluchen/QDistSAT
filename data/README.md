# Benchmark matrices

Files use the same layout as [DistQLDPC](https://github.com/guluchen/DistQLDPC):

| Suffix | Role |
|--------|------|
| `_Hx.txt`, `_Hz.txt` | CSS parity checks |
| `_Gx.txt`, `_Gz.txt` | Logical-operator bases (from `precompute-logicals`) |

Each line is a binary row (`0` / `1`, space-separated).

**Stem names** use `{family}_{n}_{k}_{d}` with family in `BB`, `GB`, `LP`, `TN`:
`n` = code length (columns of `Hx`), `k` = number of logical qubits (rows of `Gx`),
`d` = certified minimum distance, or `unknown` when it is not certified
(`BB_360_12_unknown`). The `unknown` spelling avoids reserved filename characters on
Windows. `GB_*` keeps its own prefix (not merged into `BB_*`); former `QT_*` stems and
the former `QT`/`QT2` directories are now `TN`. See [NOTICE](../NOTICE) for upstream IDs
(e.g. codeDistancePYPI `AJ_*` / `xu_*` renamed to `LP_*`).

## Tiers

Matrices live in difficulty tiers `data/tier0` … `data/tier5` (each stem is in exactly
one tier). The tier assignment is shared with DistQLDPC; codes that ship only in
DistQLDPC are not copied here.

| Tier | Purpose / per-run budget | Stems in this repository |
|------|--------------------------|--------------------------|
| `tier0` | correctness / smoke (small) | BB_72_12_6, LP_34_20_2, LP_136_32_4, TN_36_8_3, TN_36_8_4, TN_54_11_4, TN_72_14_4, TN_72_8_8, TN_108_2_12, TN_200_10_10 |
| `tier1` | — | BB_90_8_10, GB_144_12_8, BB_108_8_10, LP_238_44_6 |
| `tier2` | — | LP_340_56_8 |
| `tier3` | — | BB_144_12_12, GB_144_12_12, BB_144_14_14, LP_442_68_10, LP_544_80_12, TN_144_2_13 |
| `tier4` | timeout **2000 s** | TN_250_10_15, BB_288_12_18, LP_714_100_16 |
| `tier5` | timeout **21600 s** (6 h) | BB_360_12_unknown, LP_1768_224_unknown, TN_360_4_unknown |

Note: DistQLDPC lists the tier5 code `TN_360_4_unknown` as `TN_360_4_24`; the
difference is unresolved and the QDistSAT name is kept until it is cross-checked.

Previous layout (before the tiers): `data/BB`, `data/BB2`, `data/LP`, `data/LP2`,
`data/QT`, `data/QT2`. File stems are unchanged by the move; only directories changed.

All stem-based tools search `data/` recursively, so a stem resolves without naming
its tier (`--stem`, `--stems`, `precompute-logicals STEM`,
`benchmarks/compare_distqldpc_binaries.py --data-root data --stems …`).

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

Default root: `data/` (`--benchmark-dir` or `--stems-dir`; recurses into `tier0` … `tier5`).

## Running the tiers

Use `--stems-dir data` to benchmark every stem (recursive search), or
`--stems-dir data/tier0` for a single tier.

Run all six tiers in parallel (one process and one log per tier directory):

```bash
source venv/bin/activate   # or: export PYTHON=$PWD/venv/bin/python
pip install -e ".[dev]"
./scripts/run_benchmark_six_stemdirs.sh                    # tier0 … tier5; -d 20; splits (nproc−4)/6 --jobs per dir
./scripts/run_benchmark_six_stemdirs.sh --jobs-total 120   # ~20 workers × 6 dirs
./scripts/run_benchmark_six_stemdirs.sh --tiers "tier0 tier1 tier2" -t 120 --foreground
./scripts/run_benchmark_six_stemdirs.sh --tier-timeouts    # tier4 2000 s, tier5 21600 s per config
```
