#!/usr/bin/env bash
# Run benchmark_solver_performance on six experiment directories in parallel.
# Each directory gets its own background process and log file.
#
# Directories (under data/ by default): BB BB2 QT QT2 LP LP2
#
# Usage:
#   ./scripts/run_benchmark_six_stemdirs.sh
#   ./scripts/run_benchmark_six_stemdirs.sh --timeout 120
#   ./scripts/run_benchmark_six_stemdirs.sh --foreground --timeout 60
#   ./scripts/run_benchmark_six_stemdirs.sh --dry-run
#
# Logs: logs/<DIR>_bench_MMDD_HHMMSS.log
# PIDs: logs/six_stemdirs_MMDD_HHMMSS.pids
#
set -euo pipefail

DEFAULT_TIMEOUT=7200
DEFAULT_MAX_DISTANCE=20
# Cores to leave for OS / other users when auto-splitting across six directories.
DEFAULT_CPU_RESERVE=8
# Cap per-directory ProcessPool workers (configs overlap via stem-pipeline; ~42 configs/stem).
DEFAULT_JOBS_PER_DIR_CAP=48
STEM_DIRS=(BB BB2 QT QT2 LP LP2)
NUM_DIRS=${#STEM_DIRS[@]}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DATA_ROOT="${REPO_ROOT}/data"
LOG_DIR="${REPO_ROOT}/logs"
TIMEOUT="${DEFAULT_TIMEOUT}"
MAX_DISTANCE="${DEFAULT_MAX_DISTANCE}"
JOBS=""
JOBS_TOTAL=""
JOBS_PER_DIR_CAP="${BENCH_JOBS_PER_DIR_CAP:-${DEFAULT_JOBS_PER_DIR_CAP}}"
NO_AUTO_JOBS=0
USE_IDLE_CORES=1
FOREGROUND=0
DRY_RUN=0

_detect_logical_cpus() {
  if [[ -n "${SLURM_CPUS_ON_NODE:-}" ]]; then
    echo "${SLURM_CPUS_ON_NODE}"
    return
  fi
  if command -v nproc >/dev/null 2>&1; then
    nproc --all 2>/dev/null || nproc
    return
  fi
  "${PYTHON:-python3}" -c "import os; print(os.cpu_count() or 8)"
}

usage() {
  cat <<'EOF'
Usage: run_benchmark_six_stemdirs.sh [OPTIONS]

Run benchmarks on data/{BB,BB2,QT,QT2,LP,LP2} in parallel (six processes).
Uses default --solvers (all PySAT backends + distqldpc + codedistance).
Scans weights 1..D for every stem (--max-distance D, default: 20).

Options:
  -d, --max-distance D  Scan upper bound per stem (default: 20)
  -t, --timeout SEC       Per-config wall-clock timeout (default: 28800)
  -j, --jobs N        ProcessPool workers per directory (overrides auto-split)
  --jobs-total N      Split N workers across six dirs (≈ N/6 each)
  --jobs-per-dir-cap N  Max --jobs per directory (default: 48)
  --cpu-reserve N     Cores left unassigned when auto-splitting (default: 8)
  --use-nproc         Auto-split from nproc/SLURM_CPUS only (ignore idle sampling)
  --no-auto-jobs      Sequential inside each directory (--jobs 1)
  --data-root DIR     Parent of BB, BB2, … (default: REPO/data)
  --log-dir DIR       Log output directory (default: REPO/logs)
  --foreground        Wait for all six runs to finish (default: detach)
  --dry-run           Print commands without executing
  -h, --help          Show this help

Environment:
  PYTHON              Python executable (else VIRTUAL_ENV, then venv/ or .venv/)
  DATA_ROOT, LOG_DIR  Override defaults before flags
  BENCH_CPU_RESERVE   Same as --cpu-reserve when using auto-split
  BENCH_JOBS_TOTAL    Total worker slots across six dirs (overrides idle/nproc guess)
  BENCH_JOBS_PER_DIR_CAP  Per-directory cap (default 48)

Default auto-split uses psutil/loadavg idle cores (not nproc). On a ~200-idle-core
node this yields ~32 workers/dir (≈192 total) unless you set BENCH_JOBS_TOTAL.

Parallelism: six stem-dir processes × --jobs workers each (one spawn pool per dir).
Within each dir, multiple stems use --stem-pipeline (default): next stem starts when
~85%% of configs finish; stragglers continue; final log reprints stems in order.
Do not use bare --auto-jobs here — six processes would each underestimate idle CPUs.

Requires: project venv with pip install -e ".[dev]" (pysat + qecc_sat).

Examples:
  ./scripts/run_benchmark_six_stemdirs.sh
  BENCH_JOBS_TOTAL=180 ./scripts/run_benchmark_six_stemdirs.sh   # ~30 workers/dir
  ./scripts/run_benchmark_six_stemdirs.sh --jobs-total 192 --cpu-reserve 8
  ./scripts/run_benchmark_six_stemdirs.sh -t 300 --foreground
  tail -f logs/BB_bench_*.log
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--max-distance)
      MAX_DISTANCE="$2"
      shift 2
      ;;
    -t|--timeout)
      TIMEOUT="$2"
      shift 2
      ;;
    -j|--jobs)
      JOBS="$2"
      shift 2
      ;;
    --jobs-total)
      JOBS_TOTAL="$2"
      shift 2
      ;;
    --jobs-per-dir-cap)
      JOBS_PER_DIR_CAP="$2"
      shift 2
      ;;
    --cpu-reserve)
      DEFAULT_CPU_RESERVE="$2"
      shift 2
      ;;
    --use-nproc)
      USE_IDLE_CORES=0
      shift
      ;;
    --no-auto-jobs)
      NO_AUTO_JOBS=1
      shift
      ;;
    --data-root)
      DATA_ROOT="$2"
      shift 2
      ;;
    --log-dir)
      LOG_DIR="$2"
      shift 2
      ;;
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ "${DATA_ROOT}" != /* ]] && DATA_ROOT="${REPO_ROOT}/${DATA_ROOT}"
[[ "${LOG_DIR}" != /* ]] && LOG_DIR="${REPO_ROOT}/${LOG_DIR}"

# shellcheck source=_benchmark_env.sh
source "${SCRIPT_DIR}/_benchmark_env.sh"
resolve_benchmark_python "${REPO_ROOT}"
if [[ "${DRY_RUN}" -eq 0 ]]; then
  require_benchmark_python_deps "${REPO_ROOT}"
fi

cd "${REPO_ROOT}"
mkdir -p "${LOG_DIR}"

CPU_RESERVE="${BENCH_CPU_RESERVE:-${DEFAULT_CPU_RESERVE}}"
IDLE_NOTE=""
NCPU="$(_detect_logical_cpus)"
if [[ "${NO_AUTO_JOBS}" -eq 0 && -z "${JOBS}" ]]; then
  if [[ -n "${BENCH_JOBS_TOTAL:-}" ]]; then
    JOBS_TOTAL="${BENCH_JOBS_TOTAL}"
  fi
  if [[ -z "${JOBS_TOTAL}" ]]; then
    if [[ "${USE_IDLE_CORES}" -eq 1 ]]; then
      IFS=$'\t' read -r IDLE_CORES NCPU IDLE_NOTE < <(bench_estimate_idle_cpus "${REPO_ROOT}")
      JOBS_TOTAL=$(( IDLE_CORES - CPU_RESERVE ))
    else
      JOBS_TOTAL=$(( NCPU - CPU_RESERVE ))
      IDLE_NOTE="nproc/SLURM=${NCPU}"
    fi
  fi
  if [[ "${JOBS_TOTAL}" -lt 1 ]]; then
    JOBS_TOTAL=1
  fi
  JOBS=$(( JOBS_TOTAL / NUM_DIRS ))
  if [[ "${JOBS}" -lt 1 ]]; then
    JOBS=1
  fi
  if [[ "${JOBS}" -gt "${JOBS_PER_DIR_CAP}" ]]; then
    JOBS="${JOBS_PER_DIR_CAP}"
  fi
fi

TS="$(date +%m%d_%H%M%S)"
PID_FILE="${LOG_DIR}/six_stemdirs_${TS}.pids"

missing=()
for name in "${STEM_DIRS[@]}"; do
  dir="${DATA_ROOT}/${name}"
  if [[ ! -d "${dir}" ]]; then
    missing+=("${dir}")
  fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Error: missing stem directories:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 1
fi

echo "# repo=${REPO_ROOT}" >&2
echo "# python=${PYTHON}" >&2
if [[ "${NO_AUTO_JOBS}" -eq 1 ]]; then
  parallel_note="sequential per directory (--no-auto-jobs)"
else
  pool_slots=$(( JOBS * NUM_DIRS ))
  if [[ -n "${JOBS_TOTAL:-}" ]]; then
    split_src="jobs-total=${JOBS_TOTAL}"
  elif [[ -n "${IDLE_NOTE}" ]]; then
    split_src="${IDLE_NOTE}; reserve ${CPU_RESERVE}"
  else
    split_src="${NCPU} logical CPUs; reserve ${CPU_RESERVE}"
  fi
  parallel_note="--jobs ${JOBS}/dir (cap ${JOBS_PER_DIR_CAP}) → ~${pool_slots} pool slots; ${split_src}"
fi
echo "# max_distance=${MAX_DISTANCE}, timeout=${TIMEOUT}s per config, ${parallel_note}" >&2
echo "# solvers=default (all tools)" >&2
echo "# pid file: ${PID_FILE}" >&2

{
  echo "# started $(date '+%Y-%m-%dT%H:%M:%S%z')"
  echo "# max_distance=${MAX_DISTANCE} timeout=${TIMEOUT} parallel=${parallel_note}"
} > "${PID_FILE}"

pids=()
for name in "${STEM_DIRS[@]}"; do
  stems_dir="${DATA_ROOT}/${name}"
  log_path="${LOG_DIR}/${name}_bench_${TS}.log"
  cmd=(
    "${PYTHON}" benchmarks/benchmark_solver_performance.py
    --stems-dir "${stems_dir}"
    --max-distance "${MAX_DISTANCE}"
    --timeout "${TIMEOUT}"
  )
  if [[ "${NO_AUTO_JOBS}" -eq 1 ]]; then
    cmd+=(--no-auto-jobs --jobs 1)
  else
    cmd+=(--no-auto-jobs --jobs "${JOBS}")
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] ${name} -> ${log_path}"
    printf '  '; printf '%q ' "${cmd[@]}"; echo '>& "${log_path}" 2>&1 &'
    echo "${name} dry-run" >> "${PID_FILE}"
    continue
  fi

  {
    echo "# $(date '+%Y-%m-%dT%H:%M:%S%z')  $0"
    echo "# stems-dir=${stems_dir}"
    echo "# cmd: ${cmd[*]}"
  } > "${log_path}"

  "${cmd[@]}" >> "${log_path}" 2>&1 &
  pid=$!
  pids+=("${pid}")
  echo "${name} ${pid} ${log_path}" >> "${PID_FILE}"
  echo "started ${name} pid=${pid} log=${log_path}" >&2
done

if [[ "${DRY_RUN}" -eq 1 ]]; then
  exit 0
fi

if [[ "${FOREGROUND}" -eq 1 ]]; then
  fail=0
  for pid in "${pids[@]}"; do
    if ! wait "${pid}"; then
      fail=1
    fi
  done
  echo "# finished $(date '+%Y-%m-%dT%H:%M:%S%z')" >> "${PID_FILE}"
  if [[ "${fail}" -ne 0 ]]; then
    echo "One or more benchmark processes failed (see logs/)." >&2
    exit 1
  fi
  echo "All six benchmarks finished." >&2
else
  echo "Six benchmarks running in background. Monitor:" >&2
  echo "  tail -f ${LOG_DIR}/{BB,BB2,QT,QT2,LP,LP2}_bench_${TS}.log" >&2
  echo "  wait \$(awk '{print \$2}' ${PID_FILE})   # wait for all" >&2
fi
