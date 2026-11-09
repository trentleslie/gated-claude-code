---
title: "feat: Versioned hypothesis records and an Arivale research brief (hypothesize skill)"
type: feat
status: active
date: 2026-11-08
origin: docs/brainstorms/2026-11-08-hypothesis-records-and-arivale-brief-requirements.md
---

# feat: Versioned hypothesis records and an Arivale research brief

## Overview

Add one small cs-gated skill, `hypothesize`, that carries (a) the hypothesis record format (SLE core fields plus our evidence-state and resolvability extensions), (b) the Arivale research brief modeled on SLE's UK Biobank task, and (c) two stdlib-only helpers: a record checker and a dictionary variable finder. Then use it once on the gated VM to author the ceramide-transition worked example. Spike-sized: one skill, its tests, one VM session.

## Problem Frame

Stage 2 of the weekend discovery loop needs an output the gated agent can act on: is the hypothesis novel (evidence state) and can our data test it (resolvability)? SLE defines a versioned hypothesis record and a research-task framing; we adopt both without SLE's Inspire-rate score (see origin: docs/brainstorms/2026-11-08-hypothesis-records-and-arivale-brief-requirements.md).

## Requirements Trace

- R1, R2, R3: record format with SLE core fields unchanged, two namespaced extensions, append-only versions (Unit 1).
- R4, R4a: cite-don't-restate, human-reviewed egress (Units 1, 2, 4).
- R5, R6, R7, R7a: the brief as a skill, governance stated first, records under `docs/hypotheses/` (Unit 2).
- R8, R9, R10: ceramide worked example authored on the VM; evidence state from the Paperclip run; scripted, single-variable dictionary check (Units 3, 4).
- Success criteria: agent produces a record from brief + dictionary alone; clear resolvability verdict (including "undetermined"); SLE core field names intact by inspection.

## Scope Boundaries

- No gated analysis, no `submit-analysis` call (stage 3 is out of scope).
- No Inspire rate or literature-linkage scoring.
- No DiscoveryRSI install, no orchestration, no change to the gate, profiler, dictionary or disclosure rules.
- No new top-level workspace directory: records live under the existing `docs/` tree.

## Context & Research

### Relevant Code and Patterns

- Skill layout and delivery: `provision/skills/<name>/SKILL.md` plus optional `references/` and helper scripts, deployed by `provision/bin/deploy-skills` (rsync to cs-gated `~/.claude/skills`, `GCS_BOX` overrides the stale default host).
- Skill tests are text-assertion tests against `SKILL.md`: `tests/skills/test_apply_to_arivale.py`, `tests/skills/test_skill_lint.py`.
- Helper-script-in-skill precedent: `provision/skills/tre-runpack/reconcile.py` with `tests/skills/test_reconcile.py`.
- Workspace layout rule (root holds only symlinks, `docs/`, `analyses/`): `provision/workspace-CLAUDE.md`.
- Dictionary shape (`src/gated_cs/profiler/build_dictionary.py` `build()`): top level `{data_dir, sources, files}`; every profile appears under both `sources` and `files`, so a finder iterates `files` only. Per profile: `columns` (name to facts, type key `dtype`), and usually `subject_key` and `cohort_n`, which derived layers lack. Date-like columns may carry `temporal_coverage` (with a value-free `cadence` label) and, only under extra conditions (subject key present, at least k contributors, multi-event, built after 2026-07-21), `temporal_distribution`. On the VM the agent reads it at `~/analysis/dictionary.json`.

### Institutional Learnings

- Spike-sizing lesson from the hypothesis-quality spike: state the cheapest test and stop at the agreed point.
- Governance: no LLM reads raw data at any stage; the dictionary is non-disclosive but large (about 20 MB, ~36k columns), so it is searched by script, not read whole.

## Key Technical Decisions

- **One skill, `hypothesize`**: the brief is the skill body, so it reaches the VM through the existing `deploy-skills` path (see origin, R7a).
- **Record storage: one JSONL file per hypothesis lineage**, one version per line, at `docs/hypotheses/<slug>.jsonl` in the workspace. Mirrors SLE's `hypothesis-versions.jsonl` and makes append-only versioning natural.
- **No JSON Schema dependency.** A small stdlib-only `check_record.py` validates required fields, allowed extension values, parent links and the no-restated-numbers rule. `jsonschema` is not a project dependency and may be absent in cs-gated's environment.
- **Mechanical support for cite-don't-restate (R4)**: the checker flags bare numeric tokens in free-text fields (claim, plan, evidence, critique, extension notes). Exempt: backtick-quoted spans (the brief requires variable names in backticks, e.g. `Cer(d18:1/16:0)`); citation tokens matched by explicit patterns (`PMID:` plus digits, `doi:10.`, http(s) URLs, `results/` paths); and digits attached to letters (HbA1c, T2D, v2). A heuristic backstop to the human egress review, not a replacement for it.
- **Dictionary finder `find_vars.py`**: given name patterns (with lipid-name variants), returns only file name, column name, `dtype`, and a three-state longitudinal signal for that file: `present` (a date-like column has `temporal_distribution` or `temporal_coverage`, reported with its cadence label), `absent` (date-like columns exist without either facet), or `no_date_column`. Never prints histograms, counts, month ranges or category values, so R10 stays single-variable and non-disclosive. Because a missing facet can be a profiler limitation, `absent` and `no_date_column` map to resolvability `undetermined`, never `not_resolvable`.
- **Helpers are CLIs** invoked by full deployed path: `python3 ~/.claude/skills/hypothesize/check_record.py <file.jsonl>` (exit 0 on pass, non-zero with messages on fail) and `python3 ~/.claude/skills/hypothesize/find_vars.py ~/analysis/dictionary.json <patterns...>`. The skill directory holds no README.md (deploy-skills excludes it).
- **SLE field list is taken verbatim** from SLE `docs/HYPOTHESIS_DISCOVERY.md` (Outputs table): `version_id`, `parents`, `episode`, `claim`, `plan`, `alternatives`, `evidence`, `critic_score`, `critique`, `selected`; comparator/measurement and falsification criterion live inside `plan`, as SLE describes. `parents` refers to versions in the same lineage file only.
- **Evidence state comes from outside the VM**: the gated workspace has no Paperclip access, so the operator passes the Paperclip result (share link plus the one-line verdict) into the session; the record cites it.

## Open Questions

### Resolved During Planning

- Record format: JSONL per lineage (SLE-like), no JSON Schema file.
- Brief location and delivery: `provision/skills/hypothesize/`, delivered by `deploy-skills`.
- Dictionary access: agent-side `~/analysis/dictionary.json` on the VM; operator needs the ssh alias re-pointed for deploy and record copy-back.

### Deferred to Implementation

- Which Arivale table and column identify a metabolomics draw, and whether the dictionary profiles it longitudinally: discovered by `find_vars.py` during the VM session. If absent, the verdict is "undetermined" with that fact named.
- Exact lipid naming in the dictionary (e.g. `Cer(d18:1/16:0)` versus `ceramide (d18:1/16:0)` versus Metabolon names): the finder takes multiple patterns; the agent iterates.

## Output Structure

    provision/skills/hypothesize/
      SKILL.md                      the Arivale research brief + record rules
      references/hypothesis-record.md   field table (SLE core + extensions), example record
      check_record.py               stdlib record checker (fields, parents, no restated numbers)
      find_vars.py                  stdlib dictionary variable finder (names/types only)
    tests/skills/test_hypothesize.py
    tests/skills/fixtures/hypothesize/  tiny synthetic dictionary + good/bad records
    docs/examples/hypotheses/ceramide-transition.jsonl   copied back after review (Unit 4)

## Implementation Units

- [ ] **Unit 1: Record format and checker**

**Goal:** Define the hypothesis record and make compliance checkable.

**Requirements:** R1, R2, R3, R4

**Dependencies:** None

**Files:**
- Create: `provision/skills/hypothesize/references/hypothesis-record.md`
- Create: `provision/skills/hypothesize/check_record.py`
- Create: `tests/skills/fixtures/hypothesize/` (good and bad JSONL records)
- Test: `tests/skills/test_hypothesize.py`

**Approach:**
- Field table lists SLE core fields with their SLE names (`version_id`, `parents`, `episode`, `claim`, `plan`, `alternatives`, `evidence`, `critic_score`, `critique`, `selected`; plan states comparator/measurement and falsification criterion) and two extensions under one namespaced key (e.g. `x_stage2`: `evidence_state` and `resolvability`, each with a value, a source/citation and a short note).
- Allowed values (snake_case everywhere): evidence state `settled` / `contested` / `speculative` / `unanchored`; resolvability `resolvable` / `partial` / `not_resolvable` / `undetermined`.
- Resolvability also carries `variables` (backticked dictionary variable names that would test the claim), `repeat_measurements` (`present` / `absent` / `unknown`, from the finder) and `missing` (required when `undetermined`: the fact the dictionary could not answer).
- Checker rules: required core fields present; extension values in the allowed sets; every parent id refers to an earlier line; version ids unique; no numerals in free text outside citation tokens or variable names.

**Execution note:** Implement test-first; the checker's rules are the contract.

**Patterns to follow:** `provision/skills/tre-runpack/reconcile.py` and `tests/skills/test_reconcile.py`.

**Test scenarios:**
- Happy path: a two-version lineage (v2 cites v1 as parent) with valid extensions passes.
- Error path: missing `claim` fails and names the field.
- Error path: `evidence_state` "likely" (not allowed) fails.
- Error path: a parent id that does not exist, or appears later in the file, fails.
- Error path: duplicate `version_id` fails.
- Error path: evidence text "HR was 1.34 in 412 participants" fails the no-restated-numbers rule.
- Edge case: numerals inside a citation token (`results/abc123_ceramide__summary.csv`, `PMID:34555371`, a Paperclip share link) and inside variable names (`Cer(d18:1/16:0)`) pass.
- Edge case: `resolvability` `undetermined` with `missing` filled passes; `undetermined` with `missing` empty fails.
- Edge case: unquoted `Cer(d18:1/16:0)` in evidence fails; the backticked form passes; "HbA1c" and "T2D" pass; "stage 3" fails.
- Error path: `not resolvable` (space form) fails; only snake_case values are accepted.

**Verification:** The checker accepts the good fixtures, rejects each bad fixture with a specific message, and needs only the standard library.

- [ ] **Unit 2: The brief (SKILL.md)**

**Goal:** Give the cs-gated agent its research goal, governance boundary and workflow.

**Requirements:** R5, R6, R7, R7a, R4a

**Dependencies:** Unit 1 (references the record format and checker)

**Files:**
- Create: `provision/skills/hypothesize/SKILL.md`
- Test: `tests/skills/test_hypothesize.py`

**Approach:**
- Structure mirrors SLE's task: goal (PI-style programme on Arivale population multi-omics), data source at dictionary level, roles named only (lead, critic, reviser, no orchestration), outputs.
- Governance first: dictionary and synthetic only, never raw rows, tests only through the gate; records never restate Arivale numbers; records leave only by operator copy after human review; run `check_record.py` before declaring a record done.
- Workflow: `mkdir -p docs/hypotheses` (provisioning does not create it); set evidence state (from operator-supplied literature evidence) and resolvability (via `find_vars.py`; a missing longitudinal facet means `undetermined`, never `not_resolvable`) before proposing any gated test; write variable names in backticks; revise by appending a new version with a parent link; write to `docs/hypotheses/<slug>.jsonl`.
- States that the Inspire rate is not used and why, in one line.

**Patterns to follow:** frontmatter and trigger style of `provision/skills/validate/SKILL.md`; test style of `tests/skills/test_apply_to_arivale.py`.

**Test scenarios:**
- Happy path: frontmatter has `name: hypothesize` and a `/hypothesize` trigger in the description.
- Happy path: the governance section appears before the workflow section and mentions dictionary, synthetic, gate, and human review.
- Happy path: every SLE core field name and both extension names appear.
- Happy path: the brief invokes both helpers by their full deployed paths (`~/.claude/skills/hypothesize/check_record.py`, `~/.claude/skills/hypothesize/find_vars.py`) and points to `docs/hypotheses/`.
- Happy path: frontmatter has a non-empty `description` (skill lint requirement).
- Edge case: the brief contains no instruction to call `submit-analysis` for this stage (stage 3 is out of scope).

**Verification:** Skill lint (`tests/skills/test_skill_lint.py`) and the new tests pass; `deploy-skills --dest <tmp>` copies the skill with its helpers.

- [ ] **Unit 3: Dictionary variable finder**

**Goal:** Let the agent answer "does Arivale measure X, and is it longitudinal?" without reading the whole dictionary or combining coverage figures.

**Requirements:** R10, R4

**Dependencies:** None (parallel with Unit 1)

**Files:**
- Create: `provision/skills/hypothesize/find_vars.py`
- Create: `tests/skills/fixtures/hypothesize/dictionary.json` (tiny synthetic dictionary mirroring `build()` output: duplicated `sources` block, one file with `temporal_distribution`, one date column with only `temporal_coverage`, one derived layer without `subject_key`)
- Test: `tests/skills/test_hypothesize.py`

**Approach:**
- Input: dictionary path plus one or more case-insensitive patterns. Iterates `files` only, reads `dtype`, uses tolerant lookups for optional keys. Output per match: file, column, dtype, longitudinal state (`present` with cadence / `absent` / `no_date_column`). Nothing else.

**Test scenarios:**
- Happy path: patterns for two ceramide name variants find both fixture columns.
- Edge case: no match returns an empty result, not an error.
- Integration: output for a column with a histogram and category values contains none of those values (only file, column, type, temporal yes/no).
- Edge case: a file without any date-like column reports `no_date_column`.
- Edge case: a date column with only `temporal_coverage` reports `present` with its cadence.
- Edge case: the duplicated `sources` block does not produce duplicate matches.
- Error path: a derived layer without `subject_key` is searched without error.

**Verification:** On the fixture, outputs contain only the allowed keys.

- [ ] **Unit 4: VM session, ceramide worked example, copy-back**

**Goal:** Prove the brief works: the cs-gated agent authors the ceramide-transition record on the VM.

**Requirements:** R8, R9, R10, R4a; success criteria 1 and 2

**Dependencies:** Units 1 to 3 merged; gated VM located and cs-gated Claude Code signed in.

**Files:**
- Create: `docs/examples/hypotheses/ceramide-transition.jsonl` (after review)

**Approach:**
- Operator locates the active box, deploys skills, and starts a cs-gated session with only: `/hypothesize`, the hypothesis statement from the KRAKEN module wiki work, and the Paperclip evidence verdict with its share link.
- Agent writes 1 to 3 linked versions under `docs/hypotheses/ceramide-transition.jsonl`, runs `find_vars.py` and `check_record.py`.
- Operator reviews the record (no restated Arivale numbers, verdict stated), then copies it into the repo.

**Test expectation:** none -- operational session; correctness is checked by `check_record.py` and human review.

**Verification:** A checker-clean record exists with a resolvability verdict (`resolvable`, `partial`, `not_resolvable`, or `undetermined` with `missing` filled), and the agent needed no instruction beyond the brief and the dictionary.

## System-Wide Impact

- **Unchanged invariants:** the gate, dictionary, synthetic builder, sudoers bridge and disclosure rules are untouched; the skill adds files only.
- **Egress:** records stay in the cs-gated workspace (and its one-way JupyterLab mirror, already inside the raw-data boundary) until an operator copies them after review.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| VM IP drift or expired cs-gated sign-in blocks Unit 4 | Units 1 to 3 merge independently; Unit 4 waits on box access |
| Lipid naming mismatch gives a false "not resolvable" | `find_vars.py` takes multiple patterns; agent records patterns tried in the version note |
| Numeral heuristic misses a paraphrased number ("about four hundred") | Human egress review remains required (R4a) |
| Repeat draws not visible in the dictionary, or VM dictionary predates the temporal facets (2026-07-21) | `undetermined` verdict naming the missing fact (origin decision); operator notes the dictionary build date in the session |
| Dictionary symlink unreadable by cs-gated on the active box | Operator checks `~/analysis/dictionary.json` is readable as cs-gated before the Unit 4 session |

## Sources & References

- **Origin document:** docs/brainstorms/2026-11-08-hypothesis-records-and-arivale-brief-requirements.md
- SLE hypothesis discovery: github.com/Gen-Verse/Science-Last-Exam, docs/HYPOTHESIS_DISCOVERY.md (DiscoveryRSI pinned d9a3dfe)
- Related code: `provision/bin/deploy-skills`, `provision/skills/tre-runpack/`, `provision/workspace-CLAUDE.md`, `src/gated_cs/profiler/profile.py`
