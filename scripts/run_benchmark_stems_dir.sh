#!/usr/bin/env bash
# Run benchmark_solver_performance on every *_Hx.txt + *_Hz.txt pair in a directory.
# Output is tee'd to logs/<label>_bench_MMDD_HHMMSS.log (and the terminal).
#
# Usage:
#   ./scripts/run_benchmark_stems_dir.sh data/matrices/BB
#   ./scripts/run_benchmark_stems_dir.sh data/matrices
#   LOG_FILE=logs/my_run.log ./scripts/run_benchmark_stems_dir.sh data/matrices/BB
#
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 STEMS_DIR" >&2
  echo "Example: $0 data/matrices/BB" >&2
  exit 1
fi

STEMS_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -d "${STEMS_DIR}" ]]; then
  echo "Error: not a directory: ${STEMS_DIR}" >&2
  exit 1
fi

# shellcheck source=_benchmark_env.sh
source "${SCRIPT_DIR}/_benchmark_env.sh"
resolve_benchmark_python "${REPO_ROOT}"
require_benchmark_python_deps "${REPO_ROOT}"

cd "${REPO_ROOT}"

LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "${LOG_DIR}"
STEM_LABEL="$(basename "${STEMS_DIR%/}")"
if [[ -n "${LOG_FILE:-}" ]]; then
  LOG_PATH="${LOG_FILE}"
  mkdir -p "$(dirname "${LOG_PATH}")"
  [[ "${LOG_PATH}" != /* ]] && LOG_PATH="${REPO_ROOT}/${LOG_PATH}"
else
  LOG_PATH="${LOG_DIR}/${STEM_LABEL}_bench_$(date +%m%d_%H%M%S).log"
fi

echo "Logging to ${LOG_PATH}" >&2
{
  echo "# $(date '+%Y-%m-%dT%H:%M:%S%z')  $0 ${STEMS_DIR}"
  echo "# cwd=${REPO_ROOT}"
} >> "${LOG_PATH}"

"${PYTHON}" benchmarks/benchmark_solver_performance.py \
  --stems-dir "${STEMS_DIR}" \
  --timeout 28800 \
  --auto-jobs \
  -d 50 \
  --solvers \
    cryptosat \
    rc2-glucose42 \
    open-wbo \
    glucose42 \
    cadical153 \
    cashw-coreplus-mse22 \
    maxcdcl \
  2>&1 | tee -a "${LOG_PATH}"
