---
module: gate
tags: [security, threat-model, scope, sdc, deployment, rand-rra5000]
problem_type: assurance-boundary
---

# Host-boundary scope of the Gated Analysis Agent confidentiality barrier

## Problem

The Gated Analysis Agent was assessed against RAND RR-A5000-1 and its confidentiality barrier
found sound: operating-system privilege separation denies the agent user (`cs-gated`) any read
access to raw Arivale PHI, and the release gate (`gated_cs.gate.sdc.check_table`) decides which
computed outputs may cross that barrier. RAND's central finding — that safeguards depending on
model *cooperation* cannot reliably deny a determined agent — is answered structurally here:
the barrier is enforced by the kernel, not by the model's disposition, so jailbreaks, refusal
abliteration, and safeguard-rewriting are inapplicable.

That assessment covered the **agent-versus-data** boundary. It did **not** cover the host
boundary. This document makes the host boundary an explicit, separately-owned assurance gap so
it is neither silently assumed covered nor mistaken for a defect in the barrier.

## What the barrier assures

- `cs-gated` (the agent identity) cannot read raw data, the audit log, or private `cs-exec`
  outputs, and cannot write the gate script. Enforced by file ownership/permissions + the sudo
  bridge to `cs-exec`, verified byte-identical on both production VMs.
- Every analysis output is routed through `check_table` and either delivered (allow/suppress)
  or quarantined for human review (block/unclassifiable). The decision is deterministic and
  fail-closed: non-CSV, unreadable, NaN-count, oversized, identifier-named, and — after the
  residual-risk hardening — small per-person and quasi-identifier-combination tables never
  auto-release.
- Inference-by-differencing against the release decision is monitored offline
  (`gated_cs.gate.differencing`) and re-identification risk against the real cohort is assessed
  offline (`scripts/offline_reid_assess.py`); both are aggregate-only reporters.

## What the barrier does NOT assure (explicit gaps)

The barrier is a within-host privilege boundary. It assumes the host itself is trustworthy. It
does **not** defend against, and must not be represented as defending against:

- **Host-root compromise.** Anyone who is `root` (or can escalate to it) on a VM can read the
  raw data, the audit log, and private outputs directly, and can replace the gate script. Root
  is outside the barrier by construction.
- **Hypervisor / infrastructure access.** Whoever controls the hypervisor, disk images,
  snapshots, or backups can read PHI at rest irrespective of in-guest permissions.
- **SSH / remote-access misuse.** Whoever can open an interactive session as a privileged host
  user (or as `cs-exec`) can act with that user's data access. Who may become `cs-exec`, and
  who holds SSH credentials to the VMs, is an access-control policy question owned by
  operations — not something the gate enforces.
- **Physical access** to the hosts.

## Non-goals of this document

This plan documents the gap; it does **not** implement host-boundary controls. SSH hardening,
a root-access policy, `cs-exec` escalation policy, and hypervisor/backup controls are a
separate operational task with a separate owner. Treat any claim that "the agent cannot leak
PHI" as scoped to the agent-versus-data boundary above, not to a compromised host.

## Deploy parity (why it belongs to the barrier's assurance)

The assessment's evidence relied on the deployed gate being byte-identical on both VMs
(`10.0.0.16` and `10.0.0.29`). Hardening that lands in the repo but not on the VMs is not
hardening. After any change to the core enforcement modules, run
`bash scripts/verify_deploy_parity.sh` to confirm the deployed `gated_cs` core (`gate/run_analysis.py`,
`gate/sdc.py`, `gate/differencing.py`) is byte-identical across both hosts and matches the
repo's intended version. A parity failure is release-blocking.

## References

- Origin: Security Control Assessment: the Gated Analysis Agent against RAND RR-A5000-1
  (Phenome wiki).
- RAND RR-A5000-1, *Restricting AI Agent Use of Biological Tools*.
- `docs/plans/2026-07-26-001-feat-sdc-residual-risk-hardening-plan.md` (Unit 4).
