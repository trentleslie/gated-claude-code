# gated-claude-code

A code-to-data analysis boundary for sensitive tabular data. A Claude Code agent runs as an
unprivileged Linux user (`cs-gated`) that **cannot read the raw data**. It sees only a PHI-safe data
dictionary and fabricated synthetic samples, writes analysis scripts, and submits them through one
narrow bridge (`submit-analysis`). A second user (`cs-exec`) owns the data and runs a disclosure gate:
each script executes in a network-less bubblewrap sandbox against the real data, and only
disclosure-checked aggregates come back (k=5 minimum cell, 20-row cap, 50-category cap). Every
submission is written to an append-only audit log.

This README is written so an operator can point their own Claude Code agent at it and say
**"set up a gated box from this README."** The agent can do everything up to attaching real data,
including copying an existing dataset's synthetic surface from another VM. The steps that touch real
data, and the interactive Claude login, are reserved for the human operator and are marked
**HUMAN STEP**.

Background and design rationale: [`docs/wiki/gated-analysis-what-we-built.outline.md`](docs/wiki/gated-analysis-what-we-built.outline.md).
Longer prose setup guide: [`docs/wiki/gated-analysis-setup-guide.outline.md`](docs/wiki/gated-analysis-setup-guide.outline.md).
Historical provisioning log with live validation evidence: [`provision/RUNBOOK.md`](provision/RUNBOOK.md).

---

## For the setup agent: rules that override everything below

1. **Never read raw data, at any stage.** Do not `cat`, `head`, `ls -l` contents of, profile, hash
   line-by-line, or otherwise open files under any real data directory, and do not run
   `build-dictionary` yourself. A single raw value can reach your context through a printed row or a
   stack trace. When a step needs real data, stop and hand the exact command to the human operator, who
   relays back only non-disclosive output (pass/fail, row and column counts, audit findings).
2. **Do not sweep the network to find VMs.** VM IPs on the Phenome WARP network are DHCP-assigned and
   change on every reboot. Ask the operator for the current IP of every box you need. Never trust an IP
   from a config file, a doc, or this README.
3. **Confirm before overwriting.** If the target box already has `/var/gate/dict` or a `cs-gated`
   workspace with `analyses/` in it, it is a live box. Stop and ask before re-provisioning or replacing
   anything.
4. **Stop at every HUMAN STEP**, print what the operator must run, and wait. Do not try to automate the
   Claude login.
5. Finish with the handoff report at the end of this file. Report what was verified, not what was
   attempted.

---

## 0. Inputs to collect from the operator first

Ask for all of these up front; do not guess any of them.

| Input | Example | Notes |
|---|---|---|
| Target VM IP | `10.0.0.12` | The fresh box to set up. Ubuntu 22.04, root via SSH key. |
| SSH key path | `~/.ssh/id_ed25519_phenome` | Must already be authorized on the target **and** on any source VM. On Access-for-Infrastructure hosts keys are authorized per VM; port 22 open + key rejected means the key is not yet added to that VM's procedure, not a network fault. |
| `LABEL` | `arivale`, `time`, `<newdataset>` | Instance name. Drives the `claude-<LABEL>` launchers and which `provision/workspace-CLAUDE.<LABEL>.md` the analyst gets. |
| `DATA_DIR` | `/procedure/data/local_data/ARIVALE_SNAPSHOTS_2025` | Where the real data **will** live once attached. It is baked into the trusted gate wrappers at provision time, so get it right now. It may not exist yet. |
| `MIRROR_DIR` (optional) | `/procedure/claude-analysis` | Enables the one-way workspace mirror into JupyterLab. Leave empty to skip. |
| Source VM IP (optional) | `10.0.0.78` | An existing gated box whose dictionary + synthetic samples should be copied (step 4). |
| GitHub access | | This repo is private. The operator's GitHub account must be a collaborator to clone it. |

**One dataset per box.** The gate reads one `DATA_DIR` and the analyst reads one `/var/gate/dict`.
To serve two datasets, provision two boxes (or ask the repo owner before inventing a multi-dataset
layout).

---

## 1. Preflight (agent)

```bash
VM=<target-ip>; KEY=<ssh-key-path>
ssh -i "$KEY" -o IdentitiesOnly=yes root@"$VM" '
  . /etc/os-release && echo "os=$VERSION_ID";
  python3 --version;
  echo "userns=$(sysctl -n kernel.unprivileged_userns_clone 2>/dev/null || echo 1)";
  id cs-gated 2>/dev/null && echo "ALREADY PROVISIONED (cs-gated exists)";
  test -e /var/gate/dict && echo "ALREADY HAS /var/gate/dict";
  df -h / | tail -1'
```

Expect Ubuntu 22.04, Python 3.10+, `userns=1`. If either "ALREADY" line prints, stop and ask (rule 3).

## 2. Copy the repo and provision the boundary (agent)

Non-disclosive: no data is present yet. From a local clone of this repo:

```bash
git clone https://github.com/trentleslie/gated-claude-code.git && cd gated-claude-code

tar czf - --exclude=.git --exclude=.venv --exclude=__pycache__ . \
  | ssh -i "$KEY" root@"$VM" 'rm -rf /opt/gated-cs-src && mkdir -p /opt/gated-cs-src && tar xzf - -C /opt/gated-cs-src'

ssh -i "$KEY" root@"$VM" \
  "DATA_DIR='<DATA_DIR>' LABEL='<LABEL>' MIRROR_DIR='<MIRROR_DIR or empty>' \
   bash /opt/gated-cs-src/provision/provision.sh /opt/gated-cs-src"
```

`provision.sh` is idempotent and does, in order: checks user namespaces; installs build deps; builds
bubblewrap 0.11 from source (Ubuntu 22.04 apt ships 0.6.1, the sandbox needs >= 0.8); creates
`cs-exec`, `cs-gated`, and the `csbridge` group; creates `DATA_DIR` empty and `cs-exec`-only (or locks
it in place if data is already there); creates `/var/gate/{incoming,results,queue,derived}` and the
audit log; installs the gate venv at `/opt/gated-cs` from the hash-locked
`provision/requirements-gate.txt` (includes pandas, pyarrow, scipy, scikit-learn, statsmodels); installs
`submit-analysis` / `submit-derivation`, the trusted wrappers with `DATA_DIR` baked in, and the two-line
sudoers rule; builds the analyst workspace `/home/cs-gated/analysis` (CLAUDE.md + symlinks to
`/var/gate/dict` and `/var/gate/results`); installs `claude-<LABEL>`, `claude-<LABEL>-remote`,
`lock-gate-data`, `to-notebook`, the `/jupyter` command, and, if `MIRROR_DIR` is set, the
`gated-mirror-<LABEL>` systemd unit.

**New dataset?** If no `provision/workspace-CLAUDE.<LABEL>.md` exists, the analyst gets the default
Arivale orientation file. Draft a `workspace-CLAUDE.<LABEL>.md` modeled on
[`provision/workspace-CLAUDE.time.md`](provision/workspace-CLAUDE.time.md) (dataset name, join key, file
format and read pattern, cohort-size caveats) using only information the operator gives you, commit it,
and re-run step 2. Do not derive it by inspecting the data.

## 3. Verify the boundary (agent)

Run all of these. Each line states the expected result.

```bash
ssh -i "$KEY" root@"$VM" 'bash -s' <<'EOF'
set -u
g() { sudo -u cs-gated bash -c "$1" >/dev/null 2>&1 && echo "ALLOWED" || echo "DENIED"; }
# the wrapper line carries an inline comment: take only the path token after "DATA_DIR="
D=$(awk '/^DATA_DIR=/{sub(/^DATA_DIR=/, ""); print $1; exit}' /opt/gate/run-analysis)
if [ -d "$D" ]; then
  echo "raw data dir        : $(g "ls '$D'")   (expect DENIED)   [$D]"
else
  echo "raw data dir        : MISSING [$D]   (FAIL: provision should have created it; stop and report)"
fi
echo "audit log           : $(g 'cat /var/gate/audit.jsonl')   (expect DENIED)"
echo "quarantine queue    : $(g 'ls /var/gate/queue')   (expect DENIED)"
echo "derived store       : $(g 'ls /var/gate/derived')   (expect DENIED)"
echo "gate wrapper direct : $(g 'cat /opt/gate/run-analysis')   (expect DENIED)"
echo "results inbox       : $(g 'ls /var/gate/results')   (expect ALLOWED)"
echo "bwrap version       : $(/usr/local/bin/bwrap --version)"
echo "baked DATA_DIR      : $(grep -m1 ^DATA_DIR= /opt/gate/run-analysis)"
visudo -cf /etc/sudoers.d/cs-gated
EOF
```

Then a gate smoke test with **fabricated, in-script data only** (never real data):

```bash
ssh -i "$KEY" root@"$VM" 'bash -s' <<'EOF'
W=/home/cs-gated/analysis/analyses/00-smoke; install -d -o cs-gated -g cs-gated "$W"
cat > "$W/clean.py" <<'PY'
import os, pandas as pd
pd.DataFrame({"group": ["a", "b"], "n": [80, 60]}).to_csv(f"{os.environ['OUTPUT_DIR']}/smoke__clean.csv", index=False)
PY
cat > "$W/dump.py" <<'PY'
import os, pandas as pd
pd.DataFrame({"id": range(100), "v": range(100)}).to_csv(f"{os.environ['OUTPUT_DIR']}/smoke__dump.csv", index=False)
PY
cat > "$W/adversarial.py" <<'PY'
import os, socket
try: open("/var/gate/audit.jsonl", "a").write("TAMPER\n")
except Exception: pass
try:
    socket.create_connection(("1.1.1.1", 443), timeout=2).close(); net = "net_OPEN"
except Exception:
    net = "net_blocked"
open(f"{os.environ['OUTPUT_DIR']}/smoke__adv.csv", "w").write(f"k,n\n{net},100\n")
PY
chown cs-gated:cs-gated "$W"/*.py
cd "$W"
for s in clean dump adversarial; do echo "== $s"; sudo -u cs-gated submit-analysis "$s.py" 2>&1 | tail -3; done
echo "TAMPER lines in audit: $(grep -c TAMPER /var/gate/audit.jsonl)"
echo "network result      : $(cat /var/gate/results/*smoke__adv.csv 2>/dev/null | grep -o 'net_[A-Za-z]*' || echo 'NO RESULT (adversarial not released; investigate)')"
rm -rf "$W"; rm -f /var/gate/results/*smoke__*
EOF
```

Expected: `clean` released, `dump` quarantined (row count exceeds cap 20), `adversarial` released with
`TAMPER lines in audit: 0` **and** `network result: net_blocked`. Report network isolation as verified
only if you saw `net_blocked`; `net_OPEN` or no result is a failure to stop on. The sandbox binds `DATA_DIR` with
`--ro-bind-try`, so this works before any data is attached.

## 4. Transfer an existing synthetic dataset from another VM (agent, optional)

Use this when the dataset that will be attached to the new box **already has an audited dictionary on
another gated box** (for example, a new Arivale replica). The dictionary and synthetic samples are
derived from the data, not the machine, so they are valid verbatim on any box that will hold the same
data, and no re-profiling of raw data is needed.

What lives in `/var/gate/dict` on a source box:
- `dictionary.md`, `dictionary.json`: the PHI-safe data dictionary (audited before first delivery).
- `synthetic_samples/`: fabricated rows with fake `SYNTH_` join keys. No real value appears in them.
- Possibly `run_manifest.json` (build provenance: thresholds, file sha256s, pip freeze) and
  `reid_report.json` (offline re-identification assessment). **Do not copy `reid_report.json`**; it
  stays on the source box and is never placed where `cs-gated` can read it.

These artifacts are designed to be read by the analyst model, so handling them is within the rules.
They are still disclosure-controlled outputs: stream them box to box, do not leave copies on your
workstation, and do not paste them anywhere outside the two VMs.

```bash
SRC=<source-ip>; DST=<target-ip>; KEY=<ssh-key-path>

# 4a. Confirm the source really is a gated box and see what it holds (names + sizes only)
ssh -i "$KEY" root@"$SRC" 'id cs-gated && test -f /var/gate/dict/dictionary.md && echo OK-gated-box;
  ls -la /var/gate/dict; ls /var/gate/dict/synthetic_samples | wc -l;
  stat -c "%y dictionary built" /var/gate/dict/dictionary.json'

# 4b. Stream it across (nothing lands on the workstation's disk)
ssh -i "$KEY" root@"$SRC" 'tar czf - -C /var/gate --exclude=dict/reid_report.json dict' \
  | ssh -i "$KEY" root@"$DST" 'test -e /var/gate/dict && mv /var/gate/dict /root/var-gate-dict.bak-$(date -u +%Y%m%dT%H%M%SZ);
                                tar xzf - -C /var/gate'

# 4c. Re-apply the permissions cs-gated needs (readable via csbridge, not writable)
ssh -i "$KEY" root@"$DST" 'chown -R cs-exec:csbridge /var/gate/dict;
  find /var/gate/dict -type d -exec chmod 750 {} +;
  find /var/gate/dict -type f -exec chmod 640 {} +'

# 4d. Verify from the analyst side
ssh -i "$KEY" root@"$DST" 'sudo -u cs-gated bash -c "
  cd ~/analysis && head -c 300 dictionary.md >/dev/null && echo dict-readable;
  ls synthetic_samples | wc -l"'
```

Pass criteria: `dict-readable`, the synthetic file count matches the source, and the step 3 isolation
checks still show the raw data dir as DENIED. If the source dictionary is old (built before the
`temporal_distribution` facet, mid-2026), longitudinal fields read `unknown`; note that in the handoff so
the operator can decide whether to rebuild after data is attached.

The copy is valid only if the data later attached to the new box is **byte-identical** to the source
box's data. Step 6 has the human check for that.

## 5. Install Claude Code and skills for the analyst (agent), then log in (HUMAN STEP)

```bash
ssh -i "$KEY" root@"$VM" "sudo -iu cs-gated bash -lc 'curl -fsSL https://claude.ai/install.sh | bash && ~/.local/bin/claude --version'"

# optional: deploy the analyst skills from provision/skills (replicate, validate, hypothesize, ...)
GCS_BOX="$VM" GCS_KEY="$KEY" provision/bin/deploy-skills
```

**HUMAN STEP: authenticate.** The operator runs, on the VM:

```bash
claude-<LABEL>            # foreground; or claude-<LABEL>-remote for a reattachable tmux session
```

and completes the interactive login under the account that should own the analyst's usage. The login
only decides who drives the analyst and who is billed; the isolation is enforced by the OS and the
gate, not by Claude.

## 6. Attach the real data (HUMAN STEP, later)

The agent prints these for the operator and does not run them.

```bash
# 1. Mount or copy the data to DATA_DIR. Mounted snapshots usually arrive WORLD-READABLE,
#    which exposes raw data to cs-gated until locked. Lock immediately, after EVERY mount:
lock-gate-data <DATA_DIR>          # expect: "verified: cs-gated denied"
```

Then **either**:

- **(a) Dictionary was transferred in step 4:** confirm the attached data is byte-identical to the
  source box's data. Run on each box and compare the single output hash (the hash is non-disclosive):
  ```bash
  cd <DATA_DIR> && find . -type f -print0 | sort -z | xargs -0 md5sum | md5sum
  ```
  Same hash: done. Different hash: the transferred dictionary does not describe this data; do (b).
- **(b) New or changed dataset:** build into a private staging dir that `cs-gated` cannot enter (the
  analyst workspace links straight into `/var/gate/dict`, so never build there directly), audit, then
  publish:
  ```bash
  S=/var/gate/dict-staging; rm -rf "$S"; install -d -o cs-exec -g cs-exec -m 0700 "$S"
  sudo -u cs-exec /opt/gated-cs/bin/build-dictionary <DATA_DIR> --out "$S"
  sudo -u cs-exec /opt/gated-cs/bin/build-synthetic --dictionary "$S/dictionary.json" --out "$S"
  # AUDIT $S/dictionary.md and $S/synthetic_samples by eye now (criteria below). Publish only if clean:
  test -e /var/gate/dict && mv /var/gate/dict /root/var-gate-dict.bak-$(date -u +%Y%m%dT%H%M%SZ)
  rm -f "$S/reid_report.json"; mv "$S" /var/gate/dict
  chown -R cs-exec:csbridge /var/gate/dict
  find /var/gate/dict -type d -exec chmod 750 {} +; find /var/gate/dict -type f -exec chmod 640 {} +
  ```
  Audit criteria: no raw min/max, no participant IDs, no dates, emails, or free-text values; ID and
  date columns flagged sensitive; no real value in any synthetic file. Supported inputs: CSV, TSV
  (leading `#` metadata lines are handled), and Parquet (nested list/struct columns must be flattened
  first). Profiling needs a recognized subject-key column name; `--join-keys` applies to
  `build-synthetic` only. If the profiler fails, relay only the error type and column name to the agent,
  never a value.

Finally re-run the step 3 isolation check and one real-data `submit-analysis` of a safe aggregate (for
example, a row count per table) to confirm the gate reaches the data.

---

## Handoff report (agent, required at the end)

Report each item as **verified**, **not done (why)**, or **waiting on human**:

- Target VM IP and hostname, `LABEL`, baked `DATA_DIR`, `MIRROR_DIR`.
- Provision completed; bwrap version.
- Isolation matrix from step 3 (each line with its actual result).
- Gate smoke test verdicts (clean / dump / adversarial, TAMPER count, network result).
- Synthetic transfer: source IP, dictionary build date, synthetic file count on both sides, perms applied,
  `reid_report.json` excluded.
- Claude Code version for `cs-gated`; skills deployed (list).
- Waiting on human: Claude login, data attach + `lock-gate-data`, identical-data hash check or fresh
  dictionary build.

---

## Repository map

| Path | What |
|---|---|
| `src/gated_cs/profiler/` | `build-dictionary`, `build-synthetic`: PHI-safe dictionary + fabricated relational synthetic data |
| `src/gated_cs/gate/` | `run-analysis` executor, statistical disclosure control, differencing monitor, `gate-review` |
| `provision/provision.sh` | One-shot box provisioning (parameters: `DATA_DIR`, `LABEL`, `MIRROR_DIR`) |
| `provision/bin/` | `lock-gate-data`, launchers, `gated-mirror`, `to-notebook`, `deploy-skills` |
| `provision/skills/` | Skills deployed to the analyst (`deploy-skills`) |
| `provision/workspace-CLAUDE*.md` | The analyst's orientation file, per `LABEL` |
| `scripts/` | Offline re-identification assessment, deploy-parity check |
| `docs/wiki/` | Design write-up and prose setup guide |
| `docs/solutions/` | Documented fixes and gotchas |

Development: `uv sync --extra dev && uv run pytest`. Keep test venvs inside the repo, not under `/tmp`: the gate
sandbox masks `/tmp`, which causes spurious failures.
