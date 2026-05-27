# LaTeX benchmark tables

Per-stem `longtable` files generated from `benchmark_solver_performance` logs.

Regenerate (from repo root):

```bash
python3 local/scripts/benchmark_logs_to_latex_tables.py logs/*_bench_*.log --appendix
```

## Include in your paper

Preamble:

```latex
\usepackage{booktabs,longtable}
```

Appendix (main `.tex` at repo root or adjust paths):

```latex
\appendix
\section{Benchmark solver results}
\input{tables/appendix_benchmark_tables}
```

Optional: code list table lives in `local/benchmarks/benchmark_codes_table.tex` (copy here if you want everything under `tables/`).
