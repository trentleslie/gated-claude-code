#!/usr/bin/env bash
# Runs ON the box: rebuild the dictionary with current /root/gated-cs-new code, then
# re-run the offline re-id + fidelity assessment. Results stay on the box.
set -e
PY=/container/runtime/virtual_env/python3.13/venv/bin/python
export PYTHONPATH=/root/gated-cs-new
cd /root
echo "[rebuild] start $(date -u +%H:%M:%S)"
$PY -u -c "from gated_cs.profiler.build_dictionary import build; build('/procedure/data/local_data/TIME_SNAPSHOTS', out_dir='/root/claude-time-dict-assess')"
echo "[assess] start $(date -u +%H:%M:%S)"
$PY -u offline_reid_assess.py /procedure/data/local_data/TIME_SNAPSHOTS /root/claude-time-dict-assess /root/assess-report.json
echo "[done] $(date -u +%H:%M:%S)"
