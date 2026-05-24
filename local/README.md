# Local workspace (not on GitHub)

Everything under `local/` except this README is **gitignored**. Use it for experiments,
old benchmarks, and personal scripts so the repo root stays clean.

## Layout

```
local/
├── README.md           # this file (tracked)
├── benchmarks/         # one-off benchmark drivers (was scattered under benchmarks/)
├── scripts/            # personal / smoke-test scripts
├── tools/              # matrix download & generators
├── examples/           # old SAT demos
├── new_benchmark/      # literature instance builder (+ _upstream clones)
├── packages/           # qecc_distance wheel experiment
└── archive/            # zips, legacy benchmark/ tree
```

## Public benchmark (tracked in git)

```bash
python benchmarks/benchmark_solver_performance.py --stem BB_108_8_10 -d 10
```

## Local benchmarks (examples)

```bash
# from repo root; needs: pip install -e .
python local/benchmarks/benchmark_card_strategies.py --benchmark-dir data/matrices
python local/benchmarks/benchmark_bb_3_3_distance.py
```

Scripts resolve the repo root as `Path(__file__).parents[2]` (file → `local/benchmarks/` → `local/` → repo).

## Adding new experiments

Put new throwaway code under `local/` (pick a subfolder). Do **not** add paths under `local/` to git — update [docs/REPO_SCOPE.md](../docs/REPO_SCOPE.md) only if promoting something to the public tree.
