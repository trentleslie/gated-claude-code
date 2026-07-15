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

## Phase 3 — the gated Claude Science instance (DONE 2026-07-15, pending auth)

Installed on 10.0.0.50 as the unprivileged **cs-gated** user (recipe from
docs/solutions/.../claude-science-remote-warp-cloudflare-access-2026-07-06.md, adapted root->cs-gated):
- claude-science 0.1.15 binary at `/home/cs-gated/.local/bin/` (copied; needs only glibc 2.17).
- Daemon: systemd `claude-science.service` (User=cs-gated, `serve --no-browser --no-auto-update --host 127.0.0.1 --port 8002`, ExecStartPre orphan-guard). bwrap 0.11 on PATH satisfies the >=0.8 requirement.
- Proxy: systemd `claude-science-proxy.service` = caddy on `:8000`, Caddyfile at `/home/cs-gated/claude-science-proxy.Caddyfile` rewriting Host->localhost + Origin->http://localhost:8002.
- Access: WARP-direct `http://10.0.0.50:8000` (caddy). No cloudflared/DNS (public subdomain deferred = optional Cloudflare step).
- Login: `ssh root@10.0.0.50 cs-url` prints a single-use nonce URL rewritten to the WARP host. Expect ONE org-adoption re-login on first auth (recipe step G).
- Health verified: daemon :8002 -> 401, caddy :8000 -> 401, WARP 10.0.0.50:8000 -> 401 (token gate, not forbidden-host).

### OPEN integration question (validate once authenticated)
Can the claude-science agent (inside ITS OWN bwrap sandbox) invoke `submit-analysis` -> `sudo -u cs-exec`?
sudo may not work in a user namespace. If not, expose the bridge to the daemon another way (e.g. a
local unix-socket submission service the agent reaches via an approved network grant, instead of sudo).

## Phase 2 — dictionary built from REAL data (DONE 2026-07-15)

Data at `/procedure/data/local_data/ARIVALE_SNAPSHOTS_2025/` (76 TSVs, ~3.3 GB). On arrival it was
**world-readable** — locked to `root:cs-exec 750/640` (cs-gated denied) BEFORE any profiling.
Build: `sudo -u cs-exec build-dictionary <dir> --out /var/gate/dict` → 76 files, 36,005 columns, 20 MB dict.

Three real-data profiler fixes were needed (each committed + tested):
- `6fdb10e` drop non-finite (inf) values before histogram binning (a numeric col had inf).
- `f445a26` read via `skiprows` not `comment="#"` — Arivale files have 13 `#` metadata lines AND a
  microbiome file has a column literally named `#OTUs`; `comment="#"` was stripping it mid-line.
- `c7b0352` flag date columns/values as sensitive (HIPAA Safe-Harbor) — batch/deprecation dates were
  being listed as categories.

Leak audit (post-fix) — CLEAN: 0 raw min/max keys, known client-id absent, 487 sensitive cols,
**0 suspicious category values** (no dates/ids/emails leaked). Dictionary delivered to `/var/gate/dict`
(group csbridge, cs-gated-readable); verified cs-gated CAN read dictionary+synthetic, CANNOT read raw data.

## Relational, fully-fabricated synthetic (DONE 2026-07-15)

Regenerate from the clean dictionary ONLY (no raw-data read):
  `sudo -u cs-exec build-synthetic --dictionary /var/gate/dict/dictionary.json --out /var/gate/dict --id-pool-size 50`
- Join keys (public_client_id) draw from a shared pool of FABRICATED ids (SYNTH_0001..) -> cross-file joins work
  (chemistries x metabolomics -> 294 rows on synthetic).
- Every column fabricated by type (commits 969ee96 relational + eca06c0 full-fabrication): dates->fake ISO dates,
  numerics->fake numbers, safe categoricals->real vocab, safe numerics->real histogram marginals, keys->pool.
  No "<suppressed>" placeholders remain -> synthetic exercises the SAME code paths as real (max synthetic->real fidelity).
- Values are invented from dtype/name (never from real data): verified no real client id / no leaks in synthetic.
- Delivered group csbridge, cs-gated-readable. Rationale: "works on synthetic" predicts "works on real" for schema/joins/
  logic; the gate's scrubbed-error feedback on real runs closes the residual gap (OpenSAFELY-style).
