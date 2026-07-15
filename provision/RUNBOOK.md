# Provisioning Runbook — gated Claude Science

Target VM: **10.0.0.50** (Ubuntu 22.04.5, 16 cpu / 32 GB / 233 GB, unprivileged userns enabled).
Reach it: `ssh -i ~/.ssh/id_ed25519_phenome root@10.0.0.50`.

## Phase 1 — provision (pre-data-mount, non-disclosive)

1. Copy the repo to the VM:
   ```bash
   tar czf - --exclude=.git --exclude=.venv --exclude=.superpowers --exclude=__pycache__ . \
     | ssh -i ~/.ssh/id_ed25519_phenome root@10.0.0.50 \
       'rm -rf /opt/gated-cs-src && mkdir -p /opt/gated-cs-src && tar xzf - -C /opt/gated-cs-src'
   ```
2. Run `sudo bash /opt/gated-cs-src/provision/provision.sh` (creates users cs-exec/cs-gated + group csbridge,
   builds bwrap 0.11 from source, locks `/data/arivale`, wires the gate dirs + bridge + sudoers, installs the venv).

## Isolation validated live on 10.0.0.50 (2026-07-15)

Permission surface (verified as cs-gated):
- `/data/arivale` → **DENIED** · `/var/gate/audit.jsonl` → **DENIED** · `/var/gate/queue` → **DENIED**
- `/var/gate/incoming` → **writable** (drop scripts) · `/var/gate/results` → **readable** (get results)
- `/opt/gate/run-analysis` (the wrapper) → **unreadable/unexecutable directly**; reachable only via the
  one sudoers rule `cs-gated ALL=(cs-exec) NOPASSWD: /opt/gate/run-analysis`.

End-to-end gate behaviour (cs-gated `submit-analysis <script>`):
| Submitted script | Verdict | Evidence |
|---|---|---|
| clean aggregate (`a,80 / b,60`) | **released** | delivered to `results/`, cs-gated reads it |
| row dump (100 rows) | **quarantined** | `queue/`, audit: "row count 100 exceeds cap 20" |
| tiny subgroup (`count 2 < k=5`) | **suppressed** | delivered output keeps only `big,100`; audit: "suppressed 1 cells < k=5" |
| adversarial: `open('/var/gate/audit.jsonl','a')` + socket connect | **blocked** | script wrote nothing; **TAMPER count in audit = 0**; network refused under `--unshare-net` |

Sandbox (bubblewrap 0.11, wraps only the untrusted child inside `run_analysis`): `--unshare-net`
`--unshare-pid` `--new-session` `--clearenv`, data read-only, `out_dir` the only writable bind, audit/queue
**not mounted** into the child.

## Phase 2 — real data (Trent's step)

3. Mount / copy the real Arivale CSV/TSV data into `/data/arivale` (stays owned `cs-exec:cs-exec`, mode 700).
4. Build the PHI-safe dictionary as cs-exec:
   ```bash
   sudo -u cs-exec /opt/gated-cs/bin/build-dictionary /data/arivale --out /var/gate/dict
   ```
   Review `/var/gate/dict/dictionary.md` by eye; confirm no raw values before handing the dictionary to cs-gated.

## Phase 3 — the gated Claude Science instance (TODO)

5. Stand up a Claude Science daemon running **as cs-gated** (systemd + caddy Host-rewrite + cloudflared tunnel,
   mirroring the pop-os/`claude-science-vm` recipe but under the unprivileged cs-gated user), with the
   dictionary + synthetic samples as its only view of the data and `submit-analysis` as its bridge to real data.
