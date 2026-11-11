---
title: "Verification commands in an agent-executable runbook are security checks: make them falsifiable, fail closed, and enforce human gates by staging location"
date: 2026-11-11
category: best-practices
module: provision
problem_type: best_practice
component: documentation
severity: high
applies_when:
  - Writing a README or runbook that another operator's Claude Code agent will execute to stand up a gated box
  - A doc contains copy-paste isolation, permission, or network checks whose printed output is read as pass/fail
  - A check parses a config or wrapper line (grep/cut/sed) that may carry inline comments, padding, or quoting
  - A doc step requires a human audit before an artifact becomes visible to cs-gated
  - Deciding whether a doc-only PR may skip Greptile review
symptoms:
  - "Isolation check parsed DATA_DIR with grep ^DATA_DIR= | cut -d= -f2; the wrapper's inline comment made the path bogus, so ls printed DENIED even if cs-gated could read raw data (false pass)"
  - "Fresh dictionary build wrote straight into /var/gate/dict, already symlinked into the running analyst's workspace, before the human audit"
  - "Adversarial smoke test swallowed both connect success and failure, so network isolation could not be shown true or false"
  - "uv sync without --extra dev did not install pytest"
root_cause: missing_validation
resolution_type: documentation_update
related_components: [tooling, development_workflow, testing_framework]
tags: [runbook, fail-closed, false-pass, isolation-check, staging-gate, agent-executable-docs, greptile, phi]
---

# Verification commands in an agent-executable runbook are security checks

## Context

The root `README.md` (PR #23, merge `76a53f9`) is written to be handed to another operator's Claude Code
agent: "set up a gated box from this README." That agent runs every command literally and copies what
they print into a handoff report. The PR was doc-only, and the global policy lets doc-only PRs skip
Greptile to save credits. It was reviewed anyway and scored **1/5** with four valid findings, two of them
P1 security. Fix commit `30811a4` brought it to 5/5.

1. **False-pass isolation check (P1).** The check extracted the gate's data path from line 8 of
   `provision/run-analysis-wrapper`, which carries an inline comment:
   ```
   DATA_DIR=__GATED_CS_DATA_DIR__               # baked in at install by provision.sh; never from env/args
   ```
   `cut -d= -f2` returned the path plus padding and comment, `ls` on that bogus path always failed, and
   the probe printed `DENIED` whether or not `cs-gated` could read the raw data.
2. **Human-audit gate bypassed by write location (P1).** The fresh-dataset path built the dictionary
   straight into `/var/gate/dict`. The analyst workspace symlinks into that directory and the analyst was
   already running, so anything the audit would catch could already have been read.
3. **Unfalsifiable network test.** The adversarial script did `try: connect ... except: pass`, then wrote
   the same CSV either way. `TAMPER=0` covered only the audit-file attempt.
4. **Dev setup.** `uv sync` without `--extra dev` does not install pytest.

## Guidance

1. **Treat verification commands in an agent-executable doc as security controls.** The receiving agent
   reports them as "verified." A broken check becomes a confident false claim in the handoff, so it gets the
   same scrutiny as gate code.
2. **Parse against the real file, not the shape you assume.** Read the actual line (comments, padding,
   quoting, placeholders) and extract exactly one token.
3. **Fail closed.** Confirm the target exists before testing access to it. A missing target is FAIL, not
   DENIED: an access probe that cannot tell "denied" from "not there" proves nothing. Print the parsed value
   next to the verdict so a human can see what was actually probed.
4. **Emit a distinguishable positive and negative signal, plus a "no result" state.** Then require the pass
   token by name in the doc. A bare `except: pass` makes a test unfalsifiable.
5. **Enforce human-approval gates by where artifacts are written, not by step order.** "Build, then audit"
   means nothing if the build target is already readable by the party the audit protects. Build into a
   private staging dir the consumer cannot enter, audit there, then publish with `mv`.
6. **A doc-only PR that carries executable security verification is worth a review credit.** The skip
   policy assumes docs carry no logic; a runbook an agent will execute is code.

## Why This Matters

- A check that cannot fail is worse than no check: it manufactures a false "verified" that flows into the
  handoff, and fluent runbooks get less scrutiny than code.
- On a PHI box, a false `DENIED` on the raw-data probe, or unaudited dictionary output reaching the analyst,
  is a real disclosure path, not a docs nit.
- All four defects would have surfaced from one run against the real files. They were caught only because
  the PR was not skipped as doc-only.

## When to Apply

- Writing or reviewing any README, runbook, setup guide, or handoff another agent or operator will execute,
  especially ALLOWED/DENIED probes, smoke tests, and isolation checks.
- Any shell check that parses a config or script line, or any test whose expected outcome is a failure
  (denied, blocked, quarantined).
- Any workflow with a human approval between producing an artifact and someone else consuming it.
- Deciding whether a "doc-only" PR may skip Greptile.

## Examples

**Parse one token and fail closed**

Before (always prints DENIED):
```bash
echo "raw data dir        : $(g "ls '$(grep -m1 ^DATA_DIR= /opt/gate/run-analysis | cut -d= -f2)'")   (expect DENIED)"
```
After:
```bash
# the wrapper line carries an inline comment: take only the path token after "DATA_DIR="
D=$(awk '/^DATA_DIR=/{sub(/^DATA_DIR=/, ""); print $1; exit}' /opt/gate/run-analysis)
if [ -d "$D" ]; then
  echo "raw data dir        : $(g "ls '$D'")   (expect DENIED)   [$D]"
else
  echo "raw data dir        : MISSING [$D]   (FAIL: provision should have created it; stop and report)"
fi
```

**Distinguishable network signal**

Before:
```python
try: socket.create_connection(("1.1.1.1", 443), timeout=2)
except Exception: pass
open(f"{os.environ['OUTPUT_DIR']}/smoke__adv.csv", "w").write("k,n\nx,100\n")
```
After:
```python
try:
    socket.create_connection(("1.1.1.1", 443), timeout=2).close(); net = "net_OPEN"
except Exception:
    net = "net_blocked"
open(f"{os.environ['OUTPUT_DIR']}/smoke__adv.csv", "w").write(f"k,n\n{net},100\n")
```
```bash
echo "network result      : $(cat /var/gate/results/*smoke__adv.csv 2>/dev/null | grep -o 'net_[A-Za-z]*' || echo 'NO RESULT (adversarial not released; investigate)')"
```
The README now says: report network isolation as verified only on `net_blocked`; `net_OPEN` or no result
is a failure to stop on.

**Approval gate enforced by location**

Before (writes into the directory the analyst workspace links to):
```bash
sudo -u cs-exec /opt/gated-cs/bin/build-dictionary <DATA_DIR> --out /var/gate/dict
```
After:
```bash
S=/var/gate/dict-staging; rm -rf "$S"; install -d -o cs-exec -g cs-exec -m 0700 "$S"
sudo -u cs-exec /opt/gated-cs/bin/build-dictionary <DATA_DIR> --out "$S"
sudo -u cs-exec /opt/gated-cs/bin/build-synthetic --dictionary "$S/dictionary.json" --out "$S"
# AUDIT $S/dictionary.md and $S/synthetic_samples by eye now. Publish only if clean:
test -e /var/gate/dict && mv /var/gate/dict /root/var-gate-dict.bak-$(date -u +%Y%m%dT%H%M%SZ)
rm -f "$S/reid_report.json"; mv "$S" /var/gate/dict
chown -R cs-exec:csbridge /var/gate/dict
find /var/gate/dict -type d -exec chmod 750 {} +; find /var/gate/dict -type f -exec chmod 640 {} +
```

**Dev setup:** `uv sync && uv run pytest` became `uv sync --extra dev && uv run pytest`.

## Related

- [`../documentation-gaps/verify-doc-claims-against-code-2026-10-26.md`](../documentation-gaps/verify-doc-claims-against-code-2026-10-26.md):
  parent lesson. Item 7 ("a verification command is a claim too") is the same failure class; item 5
  argues doc-only PRs touching disclosure deserve review. This doc adds fail-closed checks and
  staging-enforced gates.
- [`../security/host-boundary-scope.md`](../security/host-boundary-scope.md): the agent-vs-data barrier the
  README's isolation checks exist to prove.
- [`synthetic-data-sdc-mechanical-nondisclosure-gate-2026-07-22.md`](synthetic-data-sdc-mechanical-nondisclosure-gate-2026-07-22.md):
  "audit the dictionary before disclosure"; staging-then-publish is its operational form.
- [`install-deploy-venv-from-uv-lock-2026-10-26.md`](install-deploy-venv-from-uv-lock-2026-10-26.md): `uv`
  lock and dev-extra context.
- Still stale as of this writing: `provision/RUNBOOK.md` (Phase 2 step 4 builds directly into
  `/var/gate/dict`) and `docs/wiki/gated-analysis-setup-guide.outline.md` (direct build; tells operators to
  hand-edit `DATA_DIR` in the wrapper, which `provision.sh` now bakes at install).
