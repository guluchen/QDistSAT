# Benchmark matrices

Files use the same layout as [DistQLDPC](https://github.com/guluchen/DistQLDPC):

| Suffix | Role |
|--------|------|
| `_Hx.txt`, `_Hz.txt` | CSS parity checks |
| `_Gx.txt`, `_Gz.txt` | Logical-operator bases (from `precompute-logicals`) |

Each line is a binary row (`0` / `1`, space-separated).

**Stem names** use `{family}_{n}_{k}_{d}` with family in `AMC`, `BB`, `COLOR`, `GB`, `HGP`, `LP`, `TN` (`HGP` hypergraph product, `COLOR` 6.6.6 color code, `AMC` abelian multi-cycle, 2026-11-04):
`n` = code length (columns of `Hx`), `k` = number of logical qubits (rows of `Gx`),
`d` = certified minimum distance; when it is not certified, the current proven bounds
`{lb}to{ub}` or `ge{lb}` (e.g. `TN_396_4_24to26`), updated as bounds
improve (DistQLDPC/PI decision 2026-10-11). These spellings stay portable to Windows. `GB_*` keeps its own prefix (not merged into `BB_*`); former `QT_*` stems and
the former `QT`/`QT2` directories are now `TN`. See [NOTICE](../NOTICE) for upstream IDs
(e.g. codeDistancePYPI `AJ_*` / `xu_*` renamed to `LP_*`).

## Tiers

Matrices live in difficulty tiers `data/tier0` … `data/tier5` (each stem is in exactly
one tier). The tier assignment and the full benchmark set are shared with DistQLDPC
(all 80 stems; the 24 remaining tier5 stems were mirrored on 2026-10-23, see NOTICE 2d; the 24 DistQLDPC library codes on 2026-11-04, NOTICE 2e).

| Tier | Purpose / per-run budget | Stems in this repository |
|------|--------------------------|--------------------------|
Tier assignment (PI 2026-10-12, mirrored from DistQLDPC): by DistQLDPC main's time on yfclab2, slower of no-card / card-mto.

| `tier0` | correctness / smoke; DistQLDPC main < 1 s on yfclab2 | AMC_108_6_9, AMC_216_6_12, AMC_330_6_14, BB_108_8_10, BB_120_8_12, BB_144_12_12, BB_30_4_6, BB_72_12_6, BB_90_8_10, COLOR_19_1_5, COLOR_7_1_3, GB_144_12_8, HGP_106_16_4, HGP_113_1_8, HGP_13_1_3, HGP_306_36_5, HGP_41_1_5, HGP_45_9_3, LP_136_32_4, LP_238_44_6, LP_34_20_2, TN_36_8_3, TN_36_8_4, TN_54_11_4, TN_72_14_4, TN_72_8_8 |
| `tier1` | main 1–10 s on yfclab2 | AMC_438_6_17, BB_186_10_14, BB_288_12_18, COLOR_127_1_13, GB_144_12_12, HGP_265_1_12, HGP_610_64_6, LP_340_56_8, LP_442_68_10 |
| `tier2` | main 10–100 s | AMC_522_6_20, BB_144_14_14, BB_248_10_18, BB_340_16_18, LP_544_80_12, TN_108_2_12, TN_144_2_13, TN_200_10_10 |
| `tier3` | main 100–2000 s | BB_294_10_20, HGP_1261_121_6, HGP_2866_256_8, HGP_481_1_16, LP_1020_136_16, LP_714_100_16, TN_250_10_15 |
| `tier4` | main 2000–5000 s; timeout **2000 s** Mac / **5000 s** yfclab2 | (none) |
| `tier5` | main > 5000 s or unsolved; timeout **21600 s** (6 h) | BB_1080_4_34to48, BB_360_12_24, BB_756_16_32to34, BB_864_4_32to40, COLOR_1027_1_32to37, COLOR_2791_1_29to61, COLOR_331_1_21, HGP_1105_1_24, LP_1054_140_20, LP_1122_148_20, LP_1428_184_24, LP_1768_224_22, LP_2610_744_16, TN_180_2_17, TN_216_4_18, TN_252_2_21, TN_288_2_23to24, TN_324_4_23to25, TN_360_4_24, TN_396_4_24to26, TN_432_8_24to29, TN_468_4_24to29, TN_496_2_29to30, TN_504_2_25to34, TN_540_4_24to34, TN_576_2_25to37, TN_612_2_25to40, TN_648_10_23to32, TN_648_14_22to28, TN_684_2_24to29 |

Note: `TN_360_4_17to24` (was `TN_360_4_ge17`, renamed 2026-10-23 to mirror DistQLDPC): the upper bound 24
comes from a weight-24 logical found by DistQLDPC's GH-146 finder and independently GF(2)-verified
(DistQLDPC `optimization/experiments/GH-146/witnesses/`); the lower bound 17 is unchanged and the
same stem is used in both repositories.

Note: six tier5 TN stems were renamed on 2026-10-29 to mirror DistQLDPC (same matrices, upper bounds
unchanged): TN_288_2_22to24 (was `TN_288_2_9to24`), TN_324_4_22to25 (was `TN_324_4_9to25`),
TN_432_8_23to29 (was `TN_432_8_9to29`), TN_496_2_23to30 (was `TN_496_2_17to30`), TN_540_4_23to34
(was `TN_540_4_9to34`), TN_576_2_24to37 (was `TN_576_2_9to37`). The new lower bounds are certified
by DistQLDPC's optional CC engine with `-cc-aut=on` (GH-152, guluchen/DistQLDPC#152; Tanner-graph
automorphism candidates, GF(2)-verified before use) and were reproduced with a different search order
(`mrv`) on the same qubit labels (same algorithm, not an independent method; DistQLDPC
`optimization/experiments/GH-152/REPRODUCTION.md` on branch `experiment/gh-152-tanner-aut`).

Note: eight tier5 stems were renamed on 2026-10-31 to mirror DistQLDPC (same matrices, upper bounds
unchanged): TN_360_4_23to24 (was `TN_360_4_17to24`), TN_396_4_23to26 (was `TN_396_4_17to26`),
TN_504_2_24to34 (was `TN_504_2_17to34`), TN_648_10_22to32 (was `TN_648_10_9to32`) [GH-157];
BB_1080_4_32to48 (was `BB_1080_4_30to48`) [GH-162, reproduced by GH-183]; BB_756_16_32to34 (was
`BB_756_16_30to34`), BB_864_4_32to40 (was `BB_864_4_30to40`) [GH-183]; TN_496_2_27to30 (was
`TN_496_2_23to30`) [GH-181]. The new lower bounds come from DistQLDPC's optional CC engine with rules
that were opt-in when the bounds were found (`charge`, default on DistQLDPC main since
guluchen/DistQLDPC#161; `tiebreak` with `mrv` / `-cc-roworder=bfs`, guluchen/DistQLDPC#180 / #204, and
`sparse,sparseov,sparsemrv`, guluchen/DistQLDPC#203, not on DistQLDPC main), each reproduced with a
different search order or binary of the same engine (not an independent second method; details in
DistQLDPC `data/matrices/README.md`, rename history).

Note: four more tier5 stems were renamed on 2026-11-05 to mirror DistQLDPC (same matrices, upper bounds
unchanged): TN_468_4_23to29 (was `TN_468_4_17to29`), TN_612_2_24to40 (was `TN_612_2_17to40`),
TN_648_14_21to28 (was `TN_648_14_9to28`), TN_684_2_22to29 (was `TN_684_2_9to29`). The lower bounds come
from DistQLDPC's optional CC engine in the GH-217 Tier 5 runs (guluchen/DistQLDPC#217): both DistQLDPC
main's CC default and the GH-217 candidate reached them, and a relabelled run reproduced each (same
engine, not an independent second method).

Note: seven more tier5 stems were renamed on 2026-11-06 to mirror DistQLDPC (same matrices, upper bounds
unchanged): TN_324_4_23to25 (was `TN_324_4_22to25`), TN_496_2_28to30 (was `TN_496_2_27to30`),
TN_540_4_24to34 (was `TN_540_4_23to34`), TN_648_14_22to28 (was `TN_648_14_21to28`), TN_684_2_24to29
(was `TN_684_2_22to29`), COLOR_1027_1_31to37 (was `COLOR_1027_1_28to37`), COLOR_2791_1_28to61 (was
`COLOR_2791_1_26to61`). The lower bounds come from DistQLDPC's optional CC engine, mostly with the
`erasure` rule (guluchen/DistQLDPC#225, #227), and each was reached by at least two runs with different
search trees (relabelled qubits and rows, a different row order, or a different binary); same engine,
not an independent second method; details in DistQLDPC `data/matrices/README.md`, rename history.

Note: thirteen more tier5 stems were renamed on 2026-11-07 to mirror DistQLDPC (same matrices, upper bounds
unchanged): TN_360_4_24 (was `TN_360_4_23to24`; d = 24, the lower bound meets the verified upper bound),
TN_396_4_24to26 (was `TN_396_4_23to26`), TN_496_2_29to30 (was `TN_496_2_28to30`), TN_504_2_25to34 (was
`TN_504_2_24to34`), TN_648_10_23to32 (was `TN_648_10_22to32`), BB_1080_4_34to48 (was `BB_1080_4_32to48`), TN_288_2_23to24 (was `TN_288_2_22to24`), TN_432_8_24to29 (was `TN_432_8_23to29`),
TN_468_4_24to29 (was `TN_468_4_23to29`), TN_576_2_25to37 (was `TN_576_2_24to37`), TN_612_2_25to40 (was
`TN_612_2_24to40`), COLOR_1027_1_32to37 (was `COLOR_1027_1_31to37`), COLOR_2791_1_29to61 (was
`COLOR_2791_1_28to61`). Each lower bound comes from DistQLDPC's optional CC engine in 12-36 h follow-up runs
(guluchen/DistQLDPC#225) and was reached by at least two runs with different search trees (same engine,
not an independent second method; details in DistQLDPC `data/matrices/README.md`, rename history).

Note: on 2026-11-04 every stem was re-tiered by DistQLDPC main 02879a93's yfclab2 baseline (5000 s limit for all codes; DistQLDPC `optimization/baselines/SERVER.md`) and the 29 DistQLDPC library codes were mirrored (NOTICE 2e). Moves of existing stems: GB_144_12_12 and BB_288_12_18 tier2 -> tier1, TN_144_2_13 tier3 -> tier2, TN_250_10_15 tier4 -> tier3, LP_1020_136_16 tier5 -> tier3. Tier 4 is empty after this re-tier.

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
- **HGP_*, COLOR_*, AMC_*** and the twisted-torus **BB_*** library codes: original generated matrices from DistQLDPC
  (GPL-3.0-or-later; constructions credited in NOTICE 2e).
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
