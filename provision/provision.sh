#!/usr/bin/env bash
# provision.sh — stand up the gated-cs boundary on a fresh Ubuntu 22.04 VM.
# Run as root, BEFORE mounting real Arivale data. Non-disclosive: no data present.
# Confirmed working on 10.0.0.50 (Ubuntu 22.04.5, unprivileged userns enabled).
set -euo pipefail
SRC="${1:-/opt/gated-cs-src}"   # path to the copied repo on the VM

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

echo "== 4. data dir (EMPTY; Trent mounts real Arivale here later), cs-exec-only =="
mkdir -p /data/arivale
chown cs-exec:cs-exec /data/arivale
chmod 700 /data/arivale

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
install -m 0440 "$SRC/provision/sudoers.d/cs-gated" /etc/sudoers.d/cs-gated
visudo -cf /etc/sudoers.d/cs-gated

echo "== 8. cs-gated analysis workspace + orientation (CLAUDE.md, reference symlinks) =="
install -d -o cs-gated -g cs-gated -m 0755 /home/cs-gated/analysis /home/cs-gated/analysis/analyses
install -o cs-gated -g cs-gated -m 0644 "$SRC/provision/workspace-CLAUDE.md" /home/cs-gated/analysis/CLAUDE.md
# reference symlinks; dict/synthetic targets resolve once the dictionary is built (Phase 2)
for pair in "/var/gate/dict/dictionary.md dictionary.md" \
            "/var/gate/dict/dictionary.json dictionary.json" \
            "/var/gate/dict/synthetic_samples synthetic_samples" \
            "/var/gate/results results"; do
  set -- $pair
  ln -sfn "$1" "/home/cs-gated/analysis/$2"
  chown -h cs-gated:cs-gated "/home/cs-gated/analysis/$2"
done

echo "Provision complete. /data/arivale is EMPTY and cs-exec-only."
echo "Next: validate the gate (RUNBOOK), then mount real Arivale data, then build the dictionary."
