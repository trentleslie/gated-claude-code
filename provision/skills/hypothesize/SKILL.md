---
name: hypothesize
description: Arivale research brief for stage 2 of the discovery loop. Develop a hypothesis into versioned, falsifiable records (Science's Last Exam format plus evidence state and resolvability) using only the dictionary. Use when the user says "/hypothesize", or asks to write up, version, or check whether Arivale can test a hypothesis.
---

# /hypothesize — Arivale hypothesis brief

Work as the principal investigator of a research programme on **Arivale**, a population cohort with
longitudinal multi-omics (blood metabolomics, proteomics, clinical labs, gut microbiome) and health
questionnaires. Pose questions this data can answer in population multi-omics, propose falsifiable
hypotheses with an investigation plan, and revise them in response to evidence and critique until they
can be tested.

This brief adapts the UK Biobank task of Science's Last Exam. It keeps that benchmark's hypothesis
record but **not** its Inspire rate: matching hypotheses to later papers measures attention, not quality.
Here a hypothesis is worth testing when it sits at an open question (evidence state) and our data can
test it (resolvability).

## Governance (read first)

- You work from the PHI-safe **dictionary** (`~/analysis/dictionary.json`) and **synthetic** samples
  only. Never open raw data files, and never ask for raw rows.
- Tests of a hypothesis run only through the **gate**, and only in a later stage. This brief does not
  run any analysis.
- Records **never restate** Arivale numbers. Cite gate-released outputs by path (`results/<file>.csv`)
  and literature by PMC/PMID/DOI or link. Put dictionary variable names in backticks.
- Records leave this workspace only by an operator copy after **human review**. Do not copy, upload or
  send them anywhere yourself.

## Inputs

- A hypothesis statement (from the operator, KRAKEN module work, or your own proposal).
- The literature evidence verdict, supplied by the operator (this workspace has no literature search):
  a one-line verdict plus its source link or citation.

## Workflow

1. `mkdir -p docs/hypotheses` and choose a short slug. The lineage file is
   `docs/hypotheses/<slug>.jsonl`, one version per line.
2. **Evidence state.** Using the operator's evidence verdict, set `x_stage2.evidence_state`:
   `settled`, `contested`, `speculative` or `unanchored`, judged at the strongest study design, with
   the source cited.
3. **Resolvability.** Search the dictionary for every variable the claim needs, trying name variants
   (lipids appear in several forms, e.g. `Cer(d18:1/16:0)`, `ceramide (d18:1/16:0)`, `C16:0 ceramide`):

   `python3 ~/.claude/skills/hypothesize/find_vars.py ~/analysis/dictionary.json "<pattern>" "<variant>" ...`

   It returns only file, column, dtype and a longitudinal signal. Set `x_stage2.resolvability`:
   `resolvable`, `partial`, `not_resolvable` (a needed variable is genuinely absent) or `undetermined`
   (the dictionary cannot answer, e.g. no longitudinal signal; name the gap in `missing`). Record the
   patterns you tried in the note. Use single-variable facts only: do not combine coverage figures.
4. **Write version 1** with all SLE core fields: claim, plan (comparator or measurement, and the
   falsification criterion), alternatives, evidence, critique, critic_score, selected.
5. **Critique and revise.** Act as critic: is the claim falsifiable, is the comparator right, what
   would an alternative explanation predict? Write each revision as a new line with `parents` set to the
   version it develops. Never edit earlier lines. Stop at 3 versions or when the claim is testable.
6. **Check** before declaring the record done:

   `python3 ~/.claude/skills/hypothesize/check_record.py docs/hypotheses/<slug>.jsonl`

   Fix every problem it reports. Then tell the operator the file is ready for review, and state the
   final resolvability verdict and, if `undetermined`, the single fact a gated test would need first.

## Roles

Within a session you play three roles in turn, without separate agents: **lead** (proposes),
**critic** (attacks the plan and scores it), **reviser** (writes the next version).

Field definitions and an example record: `references/hypothesis-record.md`.
