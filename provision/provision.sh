#!/usr/bin/env bash
# provision.sh — stand up the gated-cs boundary on a fresh Ubuntu 22.04 VM.
# Run as root, BEFORE mounting real Arivale data. Non-disclosive: no data present.
# Confirmed working on 10.0.0.50 (Ubuntu 22.04.5, unprivileged userns enabled).
set -euo pipefail
SRC="${1:-/opt/gated-cs-src}"   # path to the copied repo on the VM
# Dataset parameters (defaults preserve the original Arivale behaviour):
#   DATA_DIR — the real data dir the gate reads (baked into the trusted wrapper, never from env at runtime).
#              If it already exists (data pre-staged, e.g. TIME under /procedure), it is LOCKED in place
#              (root:cs-exec 750/640, cs-gated denied); otherwise an empty cs-exec-only dir is created.
#   LABEL    — instance name; drives the workspace CLAUDE.md and the claude-<LABEL>* launchers.
DATA_DIR="${DATA_DIR:-/data/arivale}"
LABEL="${LABEL:-arivale}"
echo "== gated-cs provision: LABEL=$LABEL  DATA_DIR=$DATA_DIR =="

echo "== 1. prerequisites =="
# unprivileged user namespaces must be usable for non-root bwrap
[ "$(sysctl -n kernel.unprivileged_userns_clone 2>/dev/null || echo 1)" = "1" ] \
  || { echo "unprivileged_userns_clone disabled — bwrap won't work for non-root"; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq socat python3-pip python3-venv \
  build-essential meson ninja-build libcap-dev pkg-config wget

echo "== 2. build bubblewrap >=0.8 from source (Ubuntu 22.04 apt ships 0.6.1) =="
if ! /usr/local/bin/bwrap --version 2>/dev/null | grep -q '0.1[1-9]\|0.[89]'; then
  cd /tmp
  wget -qO bwrap.tar.xz "https://github.com/containers/bubblewrap/releases/download/v0.11.0/bubblewrap-0.11.0.tar.xz"
  rm -rf bubblewrap-0.11.0 && tar -xf bwrap.tar.xz && cd bubblewrap-0.11.0
  meson setup _build --prefix=/usr/local -Dman=disabled
  ninja -C _build && ninja -C _build install
fi
hash -r; /usr/local/bin/bwrap --version

echo "== 3. isolation users + shared bridge group =="
id cs-exec  &>/dev/null || useradd -m -s /bin/bash cs-exec
id cs-gated &>/dev/null || useradd -m -s /bin/bash cs-gated
groupadd -f csbridge
usermod -aG csbridge cs-exec
usermod -aG csbridge cs-gated

echo "== 4. data dir ($DATA_DIR): lock in place if pre-staged, else create empty cs-exec-only =="
if [ -d "$DATA_DIR" ] && [ -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]; then
  # Real data already present (e.g. TIME under /procedure): lock root:cs-exec, cs-gated denied.
  chown -R root:cs-exec "$DATA_DIR"
  chmod 750 "$DATA_DIR"
  find "$DATA_DIR" -type d -exec chmod 750 {} +
  find "$DATA_DIR" -type f -exec chmod 640 {} +
  echo "   locked existing data -> $(stat -c '%A %U:%G' "$DATA_DIR")"
else
  mkdir -p "$DATA_DIR"
  chown cs-exec:cs-exec "$DATA_DIR"
  chmod 700 "$DATA_DIR"
  echo "   created EMPTY cs-exec-only data dir (mount/copy real data here later, then lock-gate-data)"
fi

echo "== 5. gate working dirs =="
mkdir -p /var/gate/queue /var/gate/incoming /var/gate/results /opt/gate
: > /var/gate/audit.jsonl
chown cs-exec:cs-exec /var/gate/audit.jsonl;   chmod 0600 /var/gate/audit.jsonl   # audit: cs-exec only
chown cs-exec:cs-exec /var/gate/queue;         chmod 0700 /var/gate/queue          # quarantine: cs-exec only
chown cs-gated:csbridge /var/gate/incoming;    chmod 2750 /var/gate/incoming       # scripts in  (cs-gated -> cs-exec)
chown cs-exec:csbridge  /var/gate/results;     chmod 2750 /var/gate/results        # results out (cs-exec -> cs-gated)
mkdir -p /var/gate/derived
chown cs-exec:cs-exec /var/gate/derived; chmod 0700 /var/gate/derived   # derived store: cs-exec ONLY
chown cs-exec:csbridge  /var/gate;             chmod 0710 /var/gate                # traversable by group, not listable

echo "== 6. install the package into a venv (provides run-analysis / build-dictionary / gate-review) =="
python3 -m venv /opt/gated-cs
/opt/gated-cs/bin/pip install --quiet --upgrade pip
/opt/gated-cs/bin/pip install --quiet "$SRC"

echo "== 7. bridge: submit-analysis (cs-gated), the wrapper (root:cs-exec 0750), narrow sudoers =="
install -m 0755 "$SRC/provision/submit-analysis" /usr/local/bin/submit-analysis
install -o root -g cs-exec -m 0750 "$SRC/provision/run-analysis-wrapper" /opt/gate/run-analysis
install -m 0755 "$SRC/provision/submit-derivation" /usr/local/bin/submit-derivation
install -o root -g cs-exec -m 0750 "$SRC/provision/run-derivation-wrapper" /opt/gate/run-derivation
# bake the real data path into the trusted wrappers (stays hardcoded at runtime, not env/arg driven)
sed -i "s#__GATED_CS_DATA_DIR__#${DATA_DIR}#g" /opt/gate/run-analysis /opt/gate/run-derivation
grep -q "^DATA_DIR=${DATA_DIR}\b" /opt/gate/run-analysis || { echo "wrapper DATA_DIR bake failed" >&2; exit 1; }
install -m 0440 "$SRC/provision/sudoers.d/cs-gated" /etc/sudoers.d/cs-gated
visudo -cf /etc/sudoers.d/cs-gated
# operator helper: lock a data dir so only root+cs-exec can read it (cs-gated denied)
install -m 0755 "$SRC/provision/bin/lock-gate-data" /usr/local/bin/lock-gate-data

echo "== 8. cs-gated analysis workspace + orientation (CLAUDE.md, reference symlinks) =="
install -d -o cs-gated -g cs-gated -m 0755 /home/cs-gated/analysis /home/cs-gated/analysis/analyses
# label-specific analyst orientation if present (e.g. workspace-CLAUDE.time.md), else the default
WORKSPACE_MD="$SRC/provision/workspace-CLAUDE.${LABEL}.md"
[ -f "$WORKSPACE_MD" ] || WORKSPACE_MD="$SRC/provision/workspace-CLAUDE.md"
install -o cs-gated -g cs-gated -m 0644 "$WORKSPACE_MD" /home/cs-gated/analysis/CLAUDE.md
# reference symlinks; dict/synthetic targets resolve once the dictionary is built (Phase 2)
for pair in "/var/gate/dict/dictionary.md dictionary.md" \
            "/var/gate/dict/dictionary.json dictionary.json" \
            "/var/gate/dict/synthetic_samples synthetic_samples" \
            "/var/gate/results results"; do
  set -- $pair
  ln -sfn "$1" "/home/cs-gated/analysis/$2"
  chown -h cs-gated:cs-gated "/home/cs-gated/analysis/$2"
done

echo "== 9. operator launchers (claude-${LABEL}*): run the gated analyst as cs-gated =="
# shared launcher: become cs-gated, cd ~/analysis, exec claude (guardrails are OS-level, not Claude prompts)
cat > "/usr/local/bin/claude-${LABEL}-launch" <<'LAUNCH'
#!/usr/bin/env bash
# Launch the gated analyst as the cs-gated user. Any args are passed to claude.
exec sudo -iu cs-gated env CLAUDE_FLAGS="$*" bash -lc \
  'export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"; cd ~/analysis && exec claude $CLAUDE_FLAGS'
LAUNCH
cat > "/usr/local/bin/claude-${LABEL}" <<LAUNCH
#!/usr/bin/env bash
exec claude-${LABEL}-launch
LAUNCH
cat > "/usr/local/bin/claude-${LABEL}-remote" <<REMOTE
#!/usr/bin/env bash
# Persistent, reattachable gated analyst (tmux). Ctrl-b d to detach; re-run to reattach.
S=${LABEL}
if tmux has-session -t "\$S" 2>/dev/null; then
  echo "reattaching existing session '\$S' (Ctrl-b then d to detach)"
else
  echo "starting new session '\$S' (Ctrl-b then d to detach and leave it running)"
  tmux new-session -d -s "\$S" "claude-${LABEL}-launch --dangerously-skip-permissions"
fi
exec tmux attach -t "\$S"
REMOTE
chmod 0755 "/usr/local/bin/claude-${LABEL}" "/usr/local/bin/claude-${LABEL}-launch" "/usr/local/bin/claude-${LABEL}-remote"

echo "Provision complete (LABEL=${LABEL}). Gate reads DATA_DIR=${DATA_DIR}."
echo "Next: build the dictionary as cs-exec, validate the gate (RUNBOOK), then launch: claude-${LABEL}"
