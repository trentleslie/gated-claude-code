#!/usr/bin/env bash
# Runs ON the box: rebuild the dictionary with the gated_cs code, then run the offline
# re-id + fidelity gate. Results stay on the box. All paths override via env vars.
#
#   GATED_CS  dir containing the gated_cs package  (default /root/gated-cs-new)
#   PY        python with pandas/numpy             (default box py3.13 kernel venv)
#   DATA_DIR  real data root                       (default TIME_SNAPSHOTS)
#   OUT_DIR   dictionary + synthetic output dir    (default /root/claude-time-dict-assess)
#   REPORT    assessment report path               (default /root/assess-report.json)
set -euo pipefail

# Resolve the assessor relative to THIS script so `cd` cannot desync it from the repo
# layout (the assessor is its sibling in scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASSESS="$SCRIPT_DIR/offline_reid_assess.py"

GATED_CS="${GATED_CS:-/root/gated-cs-new}"
PY="${PY:-/container/runtime/virtual_env/python3.13/venv/bin/python}"
DATA_DIR="${DATA_DIR:-/procedure/data/local_data/TIME_SNAPSHOTS}"
OUT_DIR="${OUT_DIR:-/root/claude-time-dict-assess}"
REPORT="${REPORT:-/root/assess-report.json}"
export PYTHONPATH="$GATED_CS"

echo "[rebuild] start $(date -u +%H:%M:%S)  data=$DATA_DIR out=$OUT_DIR"
"$PY" -u -c "from gated_cs.profiler.build_dictionary import build; build('$DATA_DIR', out_dir='$OUT_DIR')"
echo "[assess] start $(date -u +%H:%M:%S)  assessor=$ASSESS"
"$PY" -u "$ASSESS" "$DATA_DIR" "$OUT_DIR" "$REPORT"
echo "[done] $(date -u +%H:%M:%S)"
