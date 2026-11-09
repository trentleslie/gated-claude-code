---
date: 2026-11-08
topic: hypothesis-records-and-arivale-brief
---

# Versioned Hypothesis Records and an Arivale Research Brief

## Problem Frame

The weekend discovery loop needs a stage-2 output that the gated analysis agent (cs-gated) can act on. The hypothesis-quality spike (closed 2026-11-02) showed that literature-attention scores do not measure hypothesis quality, so stage 2 now asks two cheaper questions: *is it novel?* (evidence state) and *can our data test it?* (resolvability). Quality evidence comes later, from stage 3 tests through the gate.

Science's Last Exam (SLE, Gen-Verse) already defines a versioned hypothesis record and a task framing (research goal, data source, data layout) for population-cohort hypothesis work, run on the DiscoveryRSI harness. Adopting both gives the cs-gated agent a standard format and a research goal, and keeps our records compatible with DiscoveryRSI tooling. SLE's own score (the Inspire rate) is explicitly not adopted: it is literature-rediscovery and has the flaw the spike exposed.

Spike-sized: a schema, one brief, one worked example. Not a framework, no orchestration.

## Requirements

**Hypothesis record**
- R1. A hypothesis version record that keeps every SLE field name unchanged: version identifier, parent versions, episode, claim, investigation plan, comparator or measurement, alternative explanations, falsification criterion, evidence, critique, critic score, selected.
- R2. Two extension fields, clearly marked as ours and separate from the SLE core: **evidence state** (settled / contested / speculative / unanchored, stated at the strongest study design, with the source of the call, e.g. a Paperclip evidence run, and its share link or result set) and **resolvability** (resolvable / partial / not resolvable / undetermined, naming the dictionary variables that would test the claim and whether repeat measurements exist for longitudinal claims).
- R3. A revision is a new version linked to its parent; earlier versions are never edited, so the development of an idea is preserved (as SLE requires).
- R4. Records never restate Arivale numbers. They may contain dictionary variable names and dictionary-level descriptions (type, whether a variable exists), external literature evidence, and *citations* to gate-released outputs (file path and hash), but not the released values themselves. This also keeps a growing version chain from accumulating differencable aggregates.
- R4a. Records leave the cs-gated workspace only by an operator copy after a human review; nothing exports them automatically. "Undetermined" resolvability names exactly what the dictionary could not answer, so the first stage-3 request is explicit.

**Arivale research brief**
- R5. One research brief for Arivale modeled on SLE's UK Biobank task: a PI-style research goal for population multi-omics, the data source described at dictionary level, the harness roles (named and described only; not implemented or orchestrated), and where hypothesis records and analyses go in the cs-gated workspace (records under `docs/hypotheses/`, which the workspace layout already allows).
- R6. The brief states the governance boundary up front: the agent works from the PHI-safe dictionary and synthetic samples, never raw rows, and tests run only through the gate.
- R7. The brief tells the agent to produce hypothesis records in the R1 to R4 format, and to set evidence state and resolvability before proposing any gated test.
- R7a. The brief ships to the VM as a small skill through the existing skills sync, the only incremental delivery path the repo has.

**Worked example**
- R8. Authored by the cs-gated agent on the VM from the brief and the dictionary alone (this is the test of the first success criterion): the ceramide-transition hypothesis from the KRAKEN module work (frailty modules sit upstream of a ceramide transition; module trajectories predict it), written as 1 to 3 linked versions that show a real revision step.
- R9. Its evidence state is taken from the Paperclip evidence run already done (supported cross-sectionally; null longitudinally in ARIC), with that run cited.
- R10. Its resolvability is checked against the real PHI-safe dictionary: which ceramide and sphingomyelin species exist (e.g. C16:0, C18:0, C24:0, C24:1), whether frailty-relevant phenotypes exist, and whether participants have repeat draws. The check reads the dictionary only, by scripted search rather than an LLM reading the whole file (it is large, and lipid names vary in form), and uses single-variable facts only: no combining of per-variable coverage figures into joint counts.

## Success Criteria
- The cs-gated agent, given only the brief and the dictionary, can produce a hypothesis record in the agreed format without further instruction.
- The ceramide example ends with a clear resolvability verdict (including "undetermined" with the missing fact named), so the go/no-go on a first stage-3 test is a one-line decision.
- Records keep SLE's core field names intact, verified by inspection against SLE's documented fields (not by installing or running DiscoveryRSI).

## Scope Boundaries
- No gated analysis is run; stage 3 is out of scope.
- No adoption of the Inspire rate or any literature-linkage score.
- No orchestration of stages 1 to 4 and no DiscoveryRSI harness install. The one new skill is the brief itself (R7a).
- No changes to the gate, the dictionary profiler or disclosure rules.

## Key Decisions
- Consumer is the cs-gated agent: it is where stage-3 tests run, so its workspace is the natural home.
- SLE core fields plus two namespaced extensions: keeps DiscoveryRSI compatibility while adding the stage-2 signals the spike showed we need.
- Stop at a resolved hypothesis record: keeps it a spike and turns the next step into a single decision.
- Cite, don't restate, plus human egress review (review finding, P0): records are agent-authored files outside the gate, so they carry citations rather than numbers, and leave only by reviewed copy.
- "Undetermined" resolvability (review finding, P1): the dictionary may not record per-participant repeat draws; a k-safe repeat-draw count is then the first stage-3 request, not part of this spike.
- Brief as a skill, records authored on the VM (review finding): reuses the existing skills sync and tests the brief directly.

## Dependencies / Assumptions
- The PHI-safe dictionary is readable for the resolvability check (it lives on the gated VM; VM IPs are dynamic).
- The Paperclip evidence result for the ceramide-frailty claim (shared link) is the evidence source for R9.

## Outstanding Questions

### Deferred to Planning
- [Affects R1, R2][Technical] Record format (JSONL per run, as SLE outputs, or one file per version) and whether a JSON Schema file is worth its carrying cost.
- [Affects R10][Technical] On the VM the agent reads `~/analysis/dictionary.json` (a symlink to the dictionary) directly; operator steps still need the ssh alias re-pointed each session because VM IPs drift.
- [Affects R10][Needs research] Which Arivale table and column identify a metabolomics draw, and whether the dictionary profiles it longitudinally.

## Next Steps
-> /ce:plan for structured implementation planning
