#!/usr/bin/env bash
# Run benchmark_solver_performance on the six benchmark tier directories in parallel.
# Each directory gets its own background process and log file.
#
# Directories (under data/ by default): tier0 tier1 tier2 tier3 tier4 tier5
# (see data/README.md for the tier table). This replaces the former family batches
# BB BB2 QT QT2 LP LP2: every stem that lived in one of those six folders now lives
# in exactly one tier folder, so the default run still covers the whole corpus.
# Use --tiers to run a subset (e.g. --tiers "tier0 tier1") and --tier-timeouts to
# apply the per-tier wall-clock limits from data/README.md (tier4 2000 s, tier5 21600 s).
#
# Usage:
#   ./scripts/run_benchmark_six_stemdirs.sh
#   ./scripts/run_benchmark_six_stemdirs.sh --timeout 120
#   ./scripts/run_benchmark_six_stemdirs.sh --foreground --timeout 60
#   ./scripts/run_benchmark_six_stemdirs.sh --dry-run
#   ./scripts/run_benchmark_six_stemdirs.sh --tiers "tier0 tier1 tier2" --timeout 300
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
STEM_DIRS=(tier0 tier1 tier2 tier3 tier4 tier5)
# Per-tier timeouts (seconds) used with --tier-timeouts; tiers not listed use --timeout.
TIER4_TIMEOUT=2000
TIER5_TIMEOUT=21600
TIER_TIMEOUTS=0

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

Run benchmarks on data/{tier0,...,tier5} in parallel (one process per tier).
Uses default --solvers (all PySAT backends + distqldpc + codedistance).
Scans weights 1..D for every stem (--max-distance D, default: 20).

Options:
  -d, --max-distance D  Scan upper bound per stem (default: 20)
  -t, --timeout SEC       Per-config wall-clock timeout (default: 7200)
  --tiers "LIST"      Space-separated tier dirs to run (default: "tier0 ... tier5")
  --tier-timeouts     Use the data/README.md tier limits: tier4 2000 s, tier5 21600 s
                      (other tiers keep --timeout)
  -j, --jobs N        ProcessPool workers per directory (overrides auto-split)
  --jobs-total N      Split N workers across the selected dirs (≈ N/#dirs each)
  --jobs-per-dir-cap N  Max --jobs per directory (default: 48)
  --cpu-reserve N     Cores left unassigned when auto-splitting (default: 8)
  --use-nproc         Auto-split from nproc/SLURM_CPUS only (ignore idle sampling)
  --no-auto-jobs      Sequential inside each directory (--jobs 1)
  --data-root DIR     Parent of tier0 … tier5 (default: REPO/data)
  --log-dir DIR       Log output directory (default: REPO/logs)
  --foreground        Wait for all runs to finish (default: detach)
  --dry-run           Print commands without executing
  -h, --help          Show this help

Environment:
  PYTHON              Python executable (else VIRTUAL_ENV, then venv/ or .venv/)
  DATA_ROOT, LOG_DIR  Override defaults before flags
  BENCH_CPU_RESERVE   Same as --cpu-reserve when using auto-split
  BENCH_JOBS_TOTAL    Total worker slots across all selected dirs (overrides idle/nproc guess)
  BENCH_JOBS_PER_DIR_CAP  Per-directory cap (default 48)

Default auto-split uses psutil/loadavg idle cores (not nproc). On a ~200-idle-core
node this yields ~32 workers/dir (≈192 total) unless you set BENCH_JOBS_TOTAL.

Parallelism: one process per tier dir × --jobs workers each (one spawn pool per dir).
Within each dir, multiple stems use --stem-pipeline (default): next stem starts when
~85%% of configs finish; stragglers continue; final log reprints stems in order.
Do not use bare --auto-jobs here — parallel processes would each underestimate idle CPUs.

Requires: project venv with pip install -e ".[dev]" (pysat + qecc_sat).

Examples:
  ./scripts/run_benchmark_six_stemdirs.sh
  BENCH_JOBS_TOTAL=180 ./scripts/run_benchmark_six_stemdirs.sh   # ~30 workers/dir
  ./scripts/run_benchmark_six_stemdirs.sh --jobs-total 192 --cpu-reserve 8
  ./scripts/run_benchmark_six_stemdirs.sh -t 300 --foreground
  ./scripts/run_benchmark_six_stemdirs.sh --tier-timeouts --foreground
  tail -f logs/tier0_bench_*.log
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
    --tiers)
      read -r -a STEM_DIRS <<< "$2"
      shift 2
      ;;
    --tier-timeouts)
      TIER_TIMEOUTS=1
      shift
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
NUM_DIRS=${#STEM_DIRS[@]}
if [[ "${NUM_DIRS}" -lt 1 ]]; then
  echo "Error: --tiers selected no directories" >&2
  exit 1
fi

timeout_for_dir() {
  if [[ "${TIER_TIMEOUTS}" -eq 1 ]]; then
    case "$1" in
      tier4) echo "${TIER4_TIMEOUT}"; return ;;
      tier5) echo "${TIER5_TIMEOUT}"; return ;;
    esac
  fi
  echo "${TIMEOUT}"
}
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
timeout_note="timeout=${TIMEOUT}s per config"
if [[ "${TIER_TIMEOUTS}" -eq 1 ]]; then
  timeout_note="${timeout_note} (tier4=${TIER4_TIMEOUT}s, tier5=${TIER5_TIMEOUT}s)"
fi
echo "# dirs=${STEM_DIRS[*]}" >&2
echo "# max_distance=${MAX_DISTANCE}, ${timeout_note}, ${parallel_note}" >&2
echo "# solvers=default (all tools)" >&2
echo "# pid file: ${PID_FILE}" >&2

{
  echo "# started $(date '+%Y-%m-%dT%H:%M:%S%z')"
  echo "# dirs=${STEM_DIRS[*]}"
  echo "# max_distance=${MAX_DISTANCE} ${timeout_note} parallel=${parallel_note}"
} > "${PID_FILE}"

pids=()
for name in "${STEM_DIRS[@]}"; do
  stems_dir="${DATA_ROOT}/${name}"
  log_path="${LOG_DIR}/${name}_bench_${TS}.log"
  dir_timeout="$(timeout_for_dir "${name}")"
  cmd=(
    "${PYTHON}" benchmarks/benchmark_solver_performance.py
    --stems-dir "${stems_dir}"
    --max-distance "${MAX_DISTANCE}"
    --timeout "${dir_timeout}"
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
  echo "All ${NUM_DIRS} tier benchmarks finished." >&2
else
  echo "${NUM_DIRS} tier benchmarks running in background. Monitor:" >&2
  for name in "${STEM_DIRS[@]}"; do
    echo "  tail -f ${LOG_DIR}/${name}_bench_${TS}.log" >&2
  done
  echo "  wait \$(awk '{print \$2}' ${PID_FILE})   # wait for all" >&2
fi
