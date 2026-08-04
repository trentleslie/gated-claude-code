#!/usr/bin/env bash
# Deploy-parity check (Unit 4, R6).
#
# Hardening is worthless if it does not reach the VMs. This script confirms the deployed
# gated_cs core enforcement modules are byte-identical (a) across both production VMs and
# (b) to the repo's intended version. It is the operational counterpart to the assessment's
# own parity evidence (sha256 of the core modules across both hosts).
#
# Run it AFTER deploying to both VMs. It exits non-zero on ANY mismatch or missing file, so it
# can gate a release. It makes NO changes and reads only file hashes — never file contents.
#
# Overridable via env vars:
#   VM1        first host          (default 10.0.0.16)
#   VM2        second host         (default 10.0.0.29)
#   SSH_USER   ssh user            (default root)
#   SSH_OPTS   extra ssh options   (default: batch mode, short connect timeout)
#   REMOTE_DIR deployed package root holding gated_cs/ (default /root/gated-cs-new/gated_cs)
#   REPO_SRC   local package root  (default: <repo>/src/gated_cs, resolved from this script)
set -euo pipefail

VM1="${VM1:-10.0.0.16}"
VM2="${VM2:-10.0.0.29}"
SSH_USER="${SSH_USER:-root}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10}"
REMOTE_DIR="${REMOTE_DIR:-/root/gated-cs-new/gated_cs}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SRC="${REPO_SRC:-$SCRIPT_DIR/../src/gated_cs}"

# Core release-enforcement modules. Keep this list in sync with any module whose bytes decide
# what crosses the barrier.
MODULES=(
  "gate/run_analysis.py"
  "gate/sdc.py"
  "gate/differencing.py"
)

# sha256 of a local file, or the literal MISSING if absent.
local_hash() {
  local path="$1"
  if [[ -f "$path" ]]; then
    sha256sum "$path" | awk '{print $1}'
  else
    echo "MISSING"
  fi
}

# first 12 hex chars of a hash, for a compact table.
short() { echo "${1:0:12}"; }

# sha256 of a remote file over ssh, or MISSING/UNREACHABLE.
remote_hash() {
  local host="$1" path="$2" out
  # shellcheck disable=SC2086
  if ! out="$(ssh $SSH_OPTS "${SSH_USER}@${host}" \
        "test -f '$path' && sha256sum '$path' | awk '{print \$1}' || echo MISSING" 2>/dev/null)"; then
    echo "UNREACHABLE"
    return
  fi
  echo "$out"
}

echo "[parity] repo=$REPO_SRC  remote=$REMOTE_DIR"
echo "[parity] hosts: $VM1, $VM2  (user=$SSH_USER)"
printf '%-24s %-14s %-14s %-14s %s\n' "module" "repo" "$VM1" "$VM2" "status"

fail=0
for m in "${MODULES[@]}"; do
  rh="$(local_hash "$REPO_SRC/$m")"
  h1="$(remote_hash "$VM1" "$REMOTE_DIR/$m")"
  h2="$(remote_hash "$VM2" "$REMOTE_DIR/$m")"

  status="OK"
  if [[ "$rh" == "MISSING" ]]; then
    status="REPO-MISSING"; fail=1
  elif [[ "$h1" != "$rh" || "$h2" != "$rh" ]]; then
    status="MISMATCH"; fail=1
  fi
  printf '%-24s %-14s %-14s %-14s %s\n' "$m" "$(short "$rh")" "$(short "$h1")" "$(short "$h2")" "$status"
done

if [[ "$fail" -ne 0 ]]; then
  echo "[parity] FAIL — deployed core is NOT byte-identical to the repo on both hosts. Release-blocking."
  exit 1
fi
echo "[parity] PASS — both VMs byte-identical to the repo on all core modules."
