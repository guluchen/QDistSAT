# MaxSAT solver binaries

Unified install location for external MaxSAT solvers used by `qecc_sat`.

## Layout

```
bin/maxsat/
  manifest.json          # solver metadata (committed)
  README.md
  cashw-coreplus/        # extracted MSE 2023 build (gitignored)
    bin/cashwmaxsatcoreplus
  open-wbo/              # optional local compile (gitignored)
    open-wbo
```

Override the root directory with:

```bash
export QEECC_SAT_MAXSAT_DIR=/path/to/maxsat
```

MSE prebuilt zips are **Linux x86-64** binaries. On macOS you may need Linux (Docker/VM) or a local build; `file` on the executable should report `ELF 64-bit`.

## Download prebuilt (MSE)

From the repo root:

```bash
python scripts/download_maxsat_solvers.py
python scripts/download_maxsat_solvers.py
python scripts/download_maxsat_solvers.py --only cashw-coreplus evalmaxsat maxcdcl
python scripts/download_maxsat_solvers.py --list
```

## Build Open-WBO (macOS / local compile)

Open-WBO is **not** in the MSE zip; compile on your machine:

```bash
python scripts/download_maxsat_solvers.py --build open-wbo
```

Requires `git`, `make`, GMP (`brew install gmp` on macOS), and a C++ compiler (Xcode CLI).
Run the build script from any directory; if `make` fails with paths under the repo root, update
the download script (it clears a stale `PWD` env var). Then benchmark with `--solvers open-wbo`.

## Python usage

Solver names match `SolverType`, e.g. `rc2-g3`, `rc2-cryptosat`, `rc2-glucose42`,
or external `cashw-coreplus`, `evalmaxsat`, `maxcdcl`, `open-wbo`, `glucose_release`:

Place a local `glucose_release` binary at `bin/maxsat/glucose_release` (flat layout; no zip).

MSE zip binaries (`linux_elf` in `manifest.json`) install on any OS but run only on **Linux x86_64**.
Off Linux they are skipped silently in benchmarks (no table rows).

```python
from qecc_sat.qecc_distance import min_distance_quantum_stabilizer_or_logicals
from qecc_sat.sat_solver import SolverType

d = min_distance_quantum_stabilizer_or_logicals(S, solver_type=SolverType.RC2_G3, max_distance=12)
```

Benchmark:

```bash
python benchmarks/benchmark_solver_performance.py --solvers rc2-g3 evalmaxsat maxcdcl open-wbo glucose_release
```
