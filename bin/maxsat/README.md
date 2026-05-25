# MaxSAT solver binaries

External MaxSAT executables used by `qecc_sat` (optional; PySAT `rc2-*` solvers need no download).

## Install (from repo root)

**Recommended** — full benchmark (also installs `z3-solver` / `cvc5` via pip):

```bash
python3 scripts/install_benchmark_deps.py
python3 scripts/install_benchmark_deps.py --list
```

MaxSAT + DistQLDPC only (Linux x86_64 for MSE zips):

```bash
python3 scripts/download_maxsat_solvers.py --bench
python3 scripts/download_maxsat_solvers.py --list
```

| Goal | Command |
|------|---------|
| All MSE zips + `open-wbo` + DistQLDPC (`bin/distqldpc`) | `--bench` |
| MSE zips only | no flags |
| DistQLDPC only | `python3 scripts/install_distqldpc.py` |
| Pick solvers | `--only maxcdcl evalmaxsat` |
| Build only Open-WBO | `--build open-wbo` |

Re-run `--bench` safely: already-installed runnable binaries are skipped unless you pass `--force`.

## Layout

```
bin/maxsat/
  manifest.json
  cashw-coreplus/...                 # from --bench
  cashw-coreplus-mse22/...
  maxcdcl/MaxCDCL/bin/maxcdcl_static
  evalmaxsat/EvalMaxSAT/bin/EvalMaxSAT
  open-wbo/open-wbo                  # compiled
```

Override root: `export QEECC_SAT_MAXSAT_DIR=/path/to/maxsat`

MSE zips are **Linux x86-64 ELF**. On macOS they install but benchmarks skip them; use Linux or [Dockerfile.bench](../../Dockerfile.bench).

## Benchmark

```bash
python3 benchmarks/benchmark_solver_performance.py --list-solvers
python3 benchmarks/benchmark_solver_performance.py --stem BB_108_8_10 -d 10 \
  --solvers rc2-glucose42 maxcdcl evalmaxsat
```
