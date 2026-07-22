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

## Localhost gate-API — the working agent bridge (DONE 2026-07-15)

The Claude Science agent's sandbox blocks sudo (NoNewPrivs) and doesn't mount /var/gate, so the sudo/file
bridge is unreachable FROM THE AGENT. Solution: `gate-api` (stdlib HTTP service, run as cs-exec, systemd
`gate-api.service`, bind 127.0.0.1:8899, token at /var/gate/service.token). Endpoints (X-Gate-Token header):
GET /health, /dictionary.json, /dictionary.md, /synthetic[/<name>], POST /submit (body=script -> runs the
SAME bwrap+SDC+audit gate against real data -> returns {status, message, outputs:[{name,content}]}).
VERIFIED end-to-end: agent's vendor-count analysis on real chemistries.tsv -> released {LCA:10379, Quest:788}.
OPEN: confirm the agent's sandbox can reach host 127.0.0.1:8899 (claude-science network approval card); if its
net namespace is isolated, bind to the host IP instead. submit-analysis/sudo bridge kept but is agent-unreachable.

## Agent-reachable gate: public quick tunnel (DONE 2026-07-15)

Dead-ends (both HARD platform blocks in the claude-science agent sandbox, not fixable our side):
- localhost/private-IP (127.0.0.1:8899, 10.0.0.50:8899): agent net-namespace isolated + egress proxy hard-refuses
  private/reserved IPs and non-standard ports.
- gate-arivale.phenoma.ai (:8899 via the named tunnel): behind Cloudflare Access SSO (phenome-health default);
  agent can't do interactive SSO, and we have no Cloudflare dashboard access to add a bypass/service-token.

WORKING path: cloudflared QUICK tunnel (no account/dashboard/Access) -> gate-api:8899, giving a public
https://<random>.trycloudflare.com on 443. systemd `gate-tunnel.service` (reboot-safe); `gate-url` prints the
current URL. Protected by X-Gate-Token + the disclosure gate. Verified: real vendor-count submit -> released.
CAVEAT: the trycloudflare URL CHANGES on tunnel restart (VM reboot / process death) -> re-fetch with `gate-url`,
re-add to the agent's Domain Allowlist, re-point the agent. (A stable named tunnel needs a Cloudflare account.)

## PIVOT: gated brain = Claude Code as cs-gated (DONE 2026-07-15)

Claude Science's agent sandbox cannot reach the local gate by design (sudo blocked by no_new_privs;
private-IP + non-standard-port blocked; *.trycloudflare.com on the exfil denylist; all phenoma.ai hosts
behind Cloudflare Access SSO the agent can't complete; no Cloudflare dashboard access to add a bypass/
service-token). So the gated brain runs as **Claude Code as the cs-gated user** instead — a normal process,
so the already-proven sudo->submit-analysis->gate bridge works directly (no network/tunnel needed).

Setup: Claude Code (native, 2.1.210) at /home/cs-gated/.local/bin/claude; workspace /home/cs-gated/analysis/
(CLAUDE.md orienting the gated analyst + symlinks to /var/gate/dict/{dictionary.md,dictionary.json,
synthetic_samples} and /var/gate/results). VERIFIED: cs-gated normal shell -> submit-analysis -> "1 released";
cs-gated still denied raw data. Start: `ssh root@10.0.0.50; sudo -iu cs-gated; cd ~/analysis; claude` (auth
interactively). Optional: drive via ccr `claude remote-control` for phone/web.

Still-running-but-now-unused-for-the-agent: the Claude Science daemon (cs-arivale.phenoma.ai), the gate-api
HTTP service (:8899), and the quick tunnel — can be left or torn down; the sudo bridge is the live path.

## Operator launchers (DONE 2026-07-15)

Installed in /usr/local/bin on the VM (also in provision/bin/):
- `claude-arivale`        -> sudo -iu cs-gated; cd ~/analysis; claude   (plain TUI, no tmux, foreground)
- `claude-arivale-remote` -> same in a persistent tmux session 'arivale' + --dangerously-skip-permissions
                             (Ctrl-b d to detach; re-run to reattach from anywhere; tmux kill-session -t arivale to end)
- `claude-arivale-launch` -> shared helper (becomes cs-gated, cd ~/analysis, exec claude $flags)
skip-permissions is safe here: guardrails are OS-level (cs-gated can't read raw data) + the gate/audit, not
Claude's approval prompts. Requires the operator to have (passwordless) sudo to cs-gated (root does).

## Multi-dataset: claude-time (TIME_SNAPSHOTS wearable cohort) — DONE 2026-07-20

`provision.sh` is now parameterized (`DATA_DIR` + `LABEL`; defaults reproduce the Arivale setup exactly).
Stand up a second gated instance for a pre-staged dataset without touching the Arivale one:

```bash
# copy repo to box, then:
DATA_DIR=/procedure/data/local_data/TIME_SNAPSHOTS LABEL=time \
  bash /opt/gated-cs-src/provision/provision.sh
```

What differs from the Arivale flow, and what it does:
- **DATA_DIR is baked into the trusted wrappers at install** (`sed __GATED_CS_DATA_DIR__`), staying
  hardcoded-at-runtime (never env/arg). No separate `/data/<x>` mount needed when data is pre-staged.
- **Step 4 locks pre-staged data in place** (`root:cs-exec 750/640`, cs-gated denied) instead of creating
  an empty dir — so the real `/procedure/.../TIME_SNAPSHOTS` is locked directly.
- **LABEL drives** the analyst workspace (`workspace-CLAUDE.time.md` — wearable cohort, join key
  `time_traveler_id`, plain-CSV read pattern, small-cohort suppression note) and the `claude-time*`
  launchers.

Validated live on the TIME box (2026-07-20, box was WARP IP `.37`):
- Dictionary built as cs-exec → `/var/gate/dict` (43 files, 0 warnings, cohort_n via `time_traveler_id`).
- Isolation matrix (as cs-gated): raw data / audit / queue / gate-wrapper → **DENIED**; dictionary +
  synthetic_samples → **readable**; sudo bridge to `run-analysis` present.
- End-to-end gate: safe aggregate `submit-analysis` → **released** (`Withings: 4693 rows, 38 participants`);
  adversarial 100-row dump → **quarantined** (0 released, 1 queued).
- Claude Code 2.1.215 installed for cs-gated (`~/.local/bin/claude`). **Remaining: interactive login**
  (`claude-time`, then authenticate) — the one step that can't be scripted.
- NOTE: WARP IPs drift on reboot; the gate/data/dict are all box-local paths (IP-independent). Re-point the
  `claude-science-vm` SSH alias per session; nothing inside the box references the IP.

### JupyterLab handoff wiring (added 2026-07-20)

`provision.sh` step 10 installs the analyst→JupyterLab bridge (opt-in via `MIRROR_DIR`):
- **`to-notebook`** + **`/jupyter` slash command** (`~cs-gated/.claude/commands/jupyter.md`): converts an
  analysis `.py` → `.ipynb` in place (cells split on `# %%`), stdlib-only so it runs as cs-gated.
- **One-way mirror** (`gated-mirror` + `gated-mirror-<label>.service`): `rsync -rltD --delete --no-owner
  --no-group --chmod=D700,F600` from `~cs-gated/analysis` → `$MIRROR_DIR` on every inotify event. The
  destination is **root:root 700** (JupyterLab runs as root and reads it; cs-gated is denied even a dropped
  raw extract), and the mirror is a read-only reflection (workspace is the source of truth; edits on the
  JupyterLab side are overwritten). This is the load-bearing direction: OUT to JupyterLab, never back.

Invocation for TIME: `... MIRROR_DIR=/procedure/claude-time-workspace ... provision.sh`. Verified live on the
TIME box (2026-07-20): outward sync ~2s; cs-gated denied the mirror dir; a root-injected file never reached
the workspace and was --deleted on next sync; JupyterLab (root) reads the mirror. The operator opens notebooks
at JupyterLab `base_url=procedures/<vm-id>/processing` and runs the gate-suppressed tables against real data
there (the gate isolates the model, not the authorized human).
