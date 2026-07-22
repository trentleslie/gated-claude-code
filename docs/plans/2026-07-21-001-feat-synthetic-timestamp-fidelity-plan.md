---
title: "feat: Synthetic Timestamp Fidelity for the TIME Data Dictionary"
type: feat
status: active
date: 2026-07-21
origin: docs/brainstorms/synthetic-timestamp-fidelity-requirements.md
---

# feat: Synthetic Timestamp Fidelity for the TIME Data Dictionary

## Overview

Teach the gated-cs profiler to capture a non-disclosive, per-column **timestamp format
descriptor** and cohort-level **temporal-structure distributions**, and teach the synthesizer
to render timestamps that match each device's real format and reproduce realistic per-subject
timelines (cadence, sessions, gaps, nightly clustering, missing days). This makes an analyst's
timestamp-handling code — written against synthetic samples behind the gate — actually exercise
the same code paths it will hit on real data.

Two structural facts drive the design:
- Synthetic samples regenerate from the **dictionary alone** (`build_synthetic_from_dictionary`),
  so every descriptor must be persisted into the dictionary and be non-disclosive by construction.
- `synthesize()` today fills columns **independently** (join key drawn i.i.d. per row), which
  cannot produce coherent per-subject timelines — a joint per-subject generation model is required.

## Problem Frame

`synthesize()` renders every timestamp column as a random date-only string (`20YY-MM-DD`,
2015–2020), ignoring device format and temporal structure. Analyst code for parsing, timezone
handling, resampling, and gap/session detection passes on these samples and breaks on real data —
the exact failure synthetic samples exist to prevent. See origin:
docs/brainstorms/synthetic-timestamp-fidelity-requirements.md.

## Requirements Trace

Format capture: **R1** per-column format descriptor · **R2** per-column/per-file (no global) ·
**R3** mixed → dominant + record minority + flag.
Cohort structure: **R4** cohort distributions (cadence, session, gap, diurnal, coverage) ·
**R5** aggregates only, clear k-anon bar · **R6** carry forward birth/DOB suppression.
Non-disclosure engineering: **R11** min-subgroup (k) gate · **R12** tail/min-count suppression ·
**R13** coarsen diurnal · **R14** enrollment-relative coverage · **R15** format-descriptor safety
(generalized template, k-anon) · **R16** ephemeral intermediates + generalized single-event guard.
Synthesis: **R7** render captured format · **R8** reproduce structure + emit every recorded format ·
**R9** dictionary-only · **R10** determinism (seed=0) · **R17** joint per-subject generation ·
**R18** sample sizing · **R19** value↔timestamp co-location.

## Scope Boundaries

- No per-subject 1:1 fidelity; synthetic subjects are fresh draws from cohort distributions.
- No value-vs-time *waveform/correlation* modeling — only co-location (R19).
- No cross-file temporal alignment (Oura vs CGM timelines need not correlate).
- Not all real-data pathologies are reproduced (DST, mid-record tz shifts, dup/out-of-order,
  clock drift, malformed/null) — bounds the "runs unmodified" claim.

### Deferred to Separate Tasks

- **Offline gated assessment (required pre-disclosure gate):** run where the real TIME data lives
  (WARP box, `/procedure/data/local_data`), before any dictionary is disclosed to an analyst. Two
  jobs: (1) directional statistical-fidelity comparison of synthetic vs real distributions; (2) the
  **real-cohort re-identification assessment** — cross-column AND cross-file triangulation over the
  actual ~37-subject pool, which CI (synthetic-fixture-only) cannot cover. This is a release
  blocker for disclosure, not merely "directional." (The IP drifts per session; re-point the
  `claude-science-vm` alias — current: `root@10.0.0.62`.)

## Context & Research

### Relevant Code and Patterns

- `src/gated_cs/profiler/profile.py` — `_attach_facets` attaches `temporal_coverage` per datetime
  column; `profile_column` sets `values_suppressed`/`sensitive`. Extend here for `format` and
  `temporal_distribution` facets.
- `src/gated_cs/profiler/temporal.py` — `is_datetime_name`, `is_birth_name`, `month_bounds`,
  `cadence_label`, cadence buckets. New distribution/format helpers mirror this module's style.
- `src/gated_cs/profiler/synthesize.py` — column-independent generator to be restructured (R17).
- `src/gated_cs/profiler/build_dictionary.py` — `build`, `_render_md`, `build_synthetic_from_dictionary`;
  serialization + md rendering + dict-only synthesis path.
- `src/gated_cs/config.py` — `Thresholds(k=5, bin_min_count=5, cardinality_cap=50, ...)`;
  **reuse `k` for R11 subgroup gate and `bin_min_count` for R12 tail/bin suppression**; add a
  diurnal block-width threshold.
- `src/gated_cs/profiler/subject_key.py` — `detect_subject_key`, `cohort_n` for per-subject grouping.
- Existing k-anon precedent: `_codebook_text` cap + `profile_column` categorical `>=k` suppression
  + `_histogram` `bin_min_count` gating — the non-disclosure units follow these.

### Institutional Learnings

- None in `docs/solutions/` (directory absent). The just-merged `is_birth_name` fix (birth-month
  leak via `temporal_coverage`) is the governing precedent: capture must never re-expose a
  quasi-identifier; R16 generalizes that guard structurally.

### External References

- None used — strong local patterns for k-anon suppression and facet capture.

## Key Technical Decisions

- **Reuse existing thresholds** (`k`, `bin_min_count`) for the non-disclosure controls rather than
  inventing parallel machinery — keeps one SDC bar across the dictionary. Rationale: origin R5/R11/R12.
- **Structural single-event guard (R16)** — treat any datetime column with ~one timestamp per
  subject (`n_timestamps ≈ cohort_n`) as single-event: no distribution capture. Generalizes the
  name-based birth guard to catch unnamed quasi-identifier dates.
- **Joint per-subject generation (R17)** — restructure `synthesize()` to emit each `id_pool`
  subject's rows as a coherent, time-ordered block. Everything else (timestamp rendering, value
  co-location) composes on top. Rationale: column-independent draws make gap/session fidelity illusory.
- **Descriptors are pure schema** — format template is a generalized strftime/regex string with no
  literal value substrings; distributions are bucketed/suppressed aggregates. Rationale: R15, R5.
- **Enrollment-relative coverage (R14)** — coverage/missing-day measured as day-N-of-study, never
  absolute calendar, so nothing finer than the accepted month-level resolution is disclosed.

## Open Questions

### Resolved During Planning

- Value↔timestamp coherence → **co-location only** (R19), resolved in brainstorm.
- Statistical tolerance → **directional offline goal, not CI gate**, resolved in brainstorm.
- Which k / bin thresholds → **reuse `Thresholds.k=5`, `bin_min_count=5`**; diurnal block width is a
  new threshold (default 4h) added to `Thresholds`.
- Cumulative-disclosure / k-anon composability posture → **mechanical k=5 controls in CI + the
  offline real-cohort re-id assessment (cross-column + cross-file) as a required pre-disclosure
  release gate.** No in-code k-budgeting for now (resolved 2026-07-21).

### Deferred to Implementation

- Distribution representation (named parametric vs empirical bucketed histograms) — pick during
  Unit 2; empirical bucketed is the likely fit (mirrors `_histogram`), but confirm against real shapes.
- Per-source archetype vs single adaptive model — start adaptive (driven by captured stats); revisit
  if CGM-continuous vs Oura-nightly need distinct handling.
- Multi-seed exposure (R10) so analysts don't overfit one realized cohort — deferred; seed=0 for now.
- Exact epoch/sub-second detection heuristics — settle against real column samples during Unit 1.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation
> specification. The implementing agent should treat it as context, not code to reproduce.*

```
PROFILE (per file, raw behind gate)
  profile_file
    ├─ profile_column         (existing: dtype, k-anon values)
    └─ _attach_facets
         ├─ temporal_coverage      (existing)
         ├─ format   ◄── Unit 1    {representation, granularity, sep, tz, template, mixed, minority[]}
         └─ temporal_distribution ◄── Unit 2  (longitudinal cols only; group-by-subject IN MEMORY,
                                               collapse → cadence/session/gap/diurnal/coverage dists;
                                               apply k-gate, tail-suppress, coarsen, enrollment-relative)
                                               │ single-event guard: n_timestamps≈cohort_n → skip
DICTIONARY (persisted, non-disclosive)  ◄── Unit 3  dictionary.json + leak-safe dictionary.md

SYNTHESIZE (dict-only)  ◄── Units 4-7
  for each SYNTH subject:               (Unit 4: joint per-subject block, ordered, deterministic)
    draw temporal params from dists  →  render timestamps in captured format  (Unit 5, all recorded formats)
                                        attach value columns to same rows      (Unit 6, co-location)
  sizing: enough rows/subject to show structure  (Unit 7)

SAFETY GATE  ◄── Unit 8  leak/k-anon/triangulation tests over dictionary.json/.md/synthetic_samples/
```

## Implementation Units

- [x] **Unit 1: Per-column timestamp format descriptor**

**Goal:** Detect and attach a non-disclosive `format` descriptor to each datetime column.
**Requirements:** R1, R2, R3, R11, R15.
**Dependencies:** None.
**Files:**
- Create: `src/gated_cs/profiler/format_detect.py`
- Modify: `src/gated_cs/profiler/profile.py` (attach `format` in `_attach_facets`)
- Test: `tests/profiler/test_format_detect.py`
**Approach:**
- Classify representation: ISO-8601 string / epoch seconds / epoch millis / other; capture
  granularity (date-only vs date-time, sub-second), separator, timezone (`Z` / offset / naive).
- Emit a generalized strftime/regex **template** — tokens only, no literal digit sequences from
  values (R15 validation before persist).
- Mixed columns: pick the dominant format, record each distinct minority format present, set
  `mixed: true`; suppress a minority format whose subject-count `< k` (R15/R11).
**Execution note:** Write the value-free-template and minority-suppression assertions first.
**Patterns to follow:** `temporal.py` regex helpers; `is_datetime_name` gating in `_attach_facets`.
**Test scenarios:**
- Happy path: ISO+`Z`, ISO+offset, space-separated datetime, date-only, epoch seconds, epoch millis
  → correct representation/tz/granularity/template each.
- Edge: mixed dominant+minority formats → both recorded, `mixed` flagged.
- Edge: minority format present in `< k` subjects → suppressed from descriptor.
- Error/safety: template contains no literal digits or value substrings (regex assertion).
- Edge: naive/local timestamps → tz classified `naive`, no offset invented.
**Verification:** each datetime column in a profiled file carries a `format` descriptor whose
template round-trips the dominant shape and contains no literal values.

- [x] **Unit 2: Cohort temporal-distribution capture (non-disclosure engineered)**

**Goal:** For longitudinal timestamp columns, capture k-safe cohort distributions.
**Requirements:** R4, R5, R11, R12, R13, R14, R16 (and R6 preserved).
**Dependencies:** Unit 1 (shares `_attach_facets`).
**Files:**
- Create: `src/gated_cs/profiler/temporal_dist.py`
- Modify: `src/gated_cs/profiler/profile.py` (attach `temporal_distribution`),
  `src/gated_cs/config.py` (add `diurnal_block_hours: int = 4`)
- Test: `tests/profiler/test_temporal_dist.py`
**Approach:**
- Build a **subject-aligned full frame** for the distribution input — `{sid: df[subject_key],
  ts: to_datetime(df[name])}` then `dropna(subset=['ts'])` — and group *that*. Do NOT reuse
  `_attach_facets`'s `sid_sample = df[subject_key].head(sample_rows)` or the standalone dropna'd
  `ts`, which lose subject alignment and truncate to a head slice (would silently distort large
  CGM files).
- Group by subject **in memory only**; compute per-subject session runs / gaps / active hours,
  then **collapse to cohort aggregates** and discard the per-subject intermediates (R16 — nothing
  per-subject persists; keep intermediates as function-local values, never printed/logged/cached).
- Distributions: cadence; session-length and gap-length as **bucketed histograms** (reuse
  `bin_min_count` per bin, R12); diurnal as **coarse blocks** (`diurnal_block_hours`, R13);
  coverage/missing-day **relative to each subject's enrollment start** (R14).
- Gates: the k-gate counts **subjects with non-null values in this specific column** (not the
  file-level `cohort_n`); if `< k`, suppress the distribution entirely (R11). Clip distribution
  extremes by **percentile** (e.g. 5th/95th), never by literal min/max — a literal bound would
  re-expose an outlier's true extreme value (R12).
- Single-event guard (R16): if the median timestamps-per-subject `<= 1` (concretely,
  `n_timestamps <= 1.1 * per_column_contributor_n`), skip distribution capture; also keep the
  existing `is_birth_name`/suppressed-column skip (R6). Tolerance is a tunable default.
**Execution note:** Characterization/test-first — write the k-gate, tail-suppression, and
"no per-subject array persists" assertions before the capture logic.
**Patterns to follow:** `_histogram` + `bin_min_count`; `cadence_label`; `is_birth_name` skip.
**Test scenarios:**
- Happy path: multi-sample-per-subject column → cadence + session/gap/diurnal/coverage present.
- Edge: per-device subgroup with `< k` subjects → distribution suppressed.
- Edge: single-event column (1 stamp/subject) → no distribution captured.
- Edge: diurnal emitted in 4-hour blocks, not 24 discrete hours.
- Safety: coverage is day-N-relative, no absolute calendar date appears.
- Safety: no per-subject list/array or timeline appears in the returned facet (ephemeral).
- Edge: distribution tails clipped / each bin ≥ `bin_min_count`.
**Verification:** longitudinal columns carry a `temporal_distribution` of bucketed aggregates that
pass k/bin gates; small subgroups and single-event columns carry none.

- [x] **Unit 3: Persist + render descriptors (dictionary.json / dictionary.md)**

**Goal:** Serialize `format` + `temporal_distribution` into the dictionary and render them
leak-safe in markdown.
**Requirements:** R5, R9, R15.
**Dependencies:** Units 1–2.
**Files:**
- Modify: `src/gated_cs/profiler/build_dictionary.py` (`_render_md`)
- Test: `tests/profiler/test_build_dictionary.py`
**Approach:**
- `dictionary.json` already serializes `prof["columns"]` (json `default=str`); confirm new facets
  round-trip. Extend `_render_md` to show the format template and a compact distribution summary
  (block-level diurnal, bucketed session/gap, coverage-rate) without emitting any raw value.
- **Pin byte-stable serialization** so `build()` and `build_synthetic_from_dictionary()` produce
  identical output (R10): stable key ordering and rounded float representation for the new
  distribution facets, so a JSON round-trip does not perturb the synthesizer's draws.
**Patterns to follow:** existing `temporal_coverage` rendering in `_render_md`.
**Test scenarios:**
- Happy path: `dictionary.json` contains `format` + `temporal_distribution`; `dictionary.md` shows
  template + distribution summary.
- Safety: no raw timestamp, no birth month, no per-subject array in json or md.
- Integration: `dictionary.json` → `build_synthetic_from_dictionary` reads descriptors with no
  raw-data read (R9 parity preserved).
**Verification:** a built dictionary contains the descriptors and its md is human-readable and leak-free.

- [x] **Unit 4: Synthesizer — joint per-subject generation model**

**Goal:** Restructure `synthesize()` to emit each synthetic subject's rows as a coherent,
time-ordered block, deterministically.
**Requirements:** R17, R10.
**Dependencies:** Unit 3 (descriptors available in prof/dict).
**Files:**
- Modify: `src/gated_cs/profiler/synthesize.py`
- Test: `tests/profiler/test_synthesize.py`
**Approach:**
- **Gate the new path:** enter joint per-subject generation only when a join-key column is present
  AND at least one column carries a `temporal_distribution` facet. Otherwise retain the current
  per-column i.i.d. filling (this keeps `add_layer_to_dictionary`'s `profile_dataframe` layers and
  keyless files working — they have no facets/subject key). This makes the rewrite hold across all
  three call sites without inventing behavior for facet-less profiles.
- When gated on: per-subject loop — allocate rows to each `id_pool` subject, draw that subject's
  temporal parameters from the captured distributions, generate an ordered timestamp sequence, then
  fill the row block. Preserve `seed=0` determinism via the existing seeded `rng`.
- **Sizing model (resolves R18 fork):** keep `n_rows` as the scalar knob/target-total; derive each
  subject's row count *deterministically* from `n_rows` + seed (variable per subject, but fully
  reproducible). This preserves the public `n_rows` parameter, byte-identical determinism, and the
  parity across the three call sites — see Unit 7 for the cross-call-site plumbing.
**Execution note:** Start from a failing test asserting rows are subject-grouped and time-ordered.
**Patterns to follow:** existing `rng`/`join_keys`/`id_pool` handling in `synthesize`.
**Test scenarios:**
- Happy path: output rows group by synthetic subject; timestamps within a subject are ordered.
- Determinism: same dictionary + seed → byte-identical output (R10).
- Edge: heterogeneity — different synthetic subjects get different parameter draws.
- Edge (facet-less fallback): a `profile_dataframe` layer (no facets/subject key) and a keyless
  file both synthesize via the legacy i.i.d. path without error (existing `test_add_layer`,
  `test_two_files_share_pool` stay green).
- Safety: join key values come only from the `SYNTH_` pool; no real ids.
**Verification:** synthetic output for a longitudinal file shows coherent per-subject timelines and
is reproducible; facet-less profiles still synthesize via the legacy path.

- [x] **Unit 5: Synthesizer — timestamp rendering from descriptor + structure**

**Goal:** Render timestamps in the captured format template and reproduce temporal structure.
**Requirements:** R7, R8.
**Dependencies:** Unit 4.
**Files:**
- Modify: `src/gated_cs/profiler/synthesize.py` (timestamp rendering helper)
- Test: `tests/profiler/test_synthesize.py`
**Approach:**
- Render each generated timestamp per the column's `format` (ISO/epoch, tz, granularity).
- Shape the per-subject sequence to the captured cadence/session/gap/diurnal/coverage within the
  month-level range. Anchor each subject's absolute start inside the captured month range, then lay
  out enrollment-relative coverage/gaps forward from it.
- **"Every recorded format" = every format surviving R15 k-suppression.** Emit at least one row for
  the dominant format and each *retained* minority format. A minority format present in `< k`
  subjects was already dropped from the descriptor (R15) and must NOT appear in synthetic samples —
  re-emitting it would re-disclose a rare (quasi-identifying) format.
- **Absent/degenerate-distribution fallback:** if a column has NO `temporal_distribution`
  (k-suppressed subgroup), render *format-correct* timestamps with degenerate structure (uniform
  within the captured month range) — never fall back to the old date-only random path. If the column
  is single-event (R16), emit exactly one timestamp per synthetic subject.
**Patterns to follow:** `temporal.py` format handling; the existing `_DATE_NAME` branch being replaced.
**Test scenarios:**
- Happy path: ISO+`Z` rendered with `T`/`Z`; epoch-seconds rendered numeric; date-only has no time.
- Edge: a *retained* minority format appears in ≥1 synthetic row; a `< k` minority format never appears.
- Edge (fallback): a k-suppressed column renders format-correct, month-ranged, structureless
  timestamps (no crash, no date-only-random regression); a single-event column emits one stamp/subject.
- Structure: timestamps fall within the captured month range; spacing ≈ captured cadence; activity
  concentrated in captured diurnal blocks; missing days appear.
**Verification:** synthetic timestamp columns match the format template and exhibit captured structure;
suppressed/single-event columns degrade gracefully while staying format-correct.

- [x] **Unit 6: Synthesizer — value↔timestamp co-location**

**Goal:** Attach value columns to the same synthetic subject/timeline so aggregation scripts work.
**Requirements:** R19.
**Dependencies:** Units 4–5.
**Files:**
- Modify: `src/gated_cs/profiler/synthesize.py`
- Test: `tests/profiler/test_synthesize.py`
**Approach:**
- Within each subject's row block, draw value columns from their existing histograms/categories so
  every row is a complete (subject, timestamp, value) tuple. No value-vs-time correlation modeling.
**Test scenarios:**
- Happy path: per-subject rows carry values; a groupby-hour / per-session mean yields non-empty output.
- Edge: values remain within their histogram bins / category sets.
- Safety: no assertion of value-vs-time correlation (co-location only).
**Verification:** resampling/session-aggregation over synthetic samples produces meaningful (non-empty)
results.

- [x] **Unit 7: Sample sizing reconciliation**

**Goal:** Ensure enough rows per synthetic subject to exhibit temporal structure.
**Requirements:** R18.
**Dependencies:** Unit 4.
**Files:**
- Modify: `src/gated_cs/profiler/build_dictionary.py` (call sites), `src/gated_cs/profiler/synthesize.py`
- Test: `tests/profiler/test_synthesize.py`, `tests/profiler/test_synthetic_from_dict.py`
**Approach:**
- Reconcile the fixed `n_rows=100` over a 50-id pool (~2 rows/subject): raise `n_rows` and/or emit
  variable rows-per-subject so sessions/gaps/diurnal manifest. Apply consistently across `build`,
  `add_layer_to_dictionary`, and `build_synthetic_from_dictionary`.
**Test scenarios:**
- Happy path: each synthetic subject has enough rows to show ≥1 session and ≥1 gap.
- Edge: variable rows-per-subject supported; total output stays bounded.
- Integration: dict-only regeneration (`build_synthetic_from_dictionary`) uses the same sizing.
**Verification:** synthetic per-subject sequences are long enough for gap/session code to have signal.

- [x] **Unit 8: Non-disclosure + triangulation test gate**

**Goal:** Lock the *mechanical* non-disclosure controls as executable CI tests. This gate verifies
the controls fire correctly on synthetic-raw fixtures; it is **not** a real-cohort re-identification
proof (that is the offline gated assessment — see Deferred to Separate Tasks, now a required
pre-disclosure gate).
**Requirements:** R5, R11–R16, plus the *safety* subset of the success criteria (leak/k-anon/no-raw-
value/triangulation-smoke). The statistical-fidelity success goal is validated offline, not here.
**Dependencies:** Units 1–7.
**Files:**
- Modify: `tests/profiler/test_time_e2e.py`
- Create: `tests/profiler/test_nondisclosure.py`
- Test: (this unit is tests)
**Approach:**
- Extend the TIME-shaped e2e: no raw timestamp value, no per-subject timeline/array, no birth month
  in `dictionary.json`/`dictionary.md`/`synthetic_samples/`; format templates are value-free;
  distributions honor k / bin / percentile-clip suppression; coverage is enrollment-relative.
- **No `< k` format leaks:** assert no timestamp format present in `< k` subjects appears in any
  disclosed artifact (descriptor or `synthetic_samples/`).
- **Process-level ephemerality (R16):** assert the per-subject intermediates never persist — capture
  stdout/stderr/logs during a build and scan for per-subject arrays/timelines, and confirm no
  intermediate temp file is written (schema-shape assertion on the facet alone is insufficient).
- **Triangulation smoke check:** over a synthetic-raw fixture with a known outlier, confirm that
  combining all disclosed distributions for a column — and across columns of the same file — does not
  narrow to a single subject. (Cross-file triangulation over the real cohort is covered by the
  offline gated assessment, not CI.)
**Execution note:** These tests encode the mechanical safety contract — treat failures as release
blockers. They do not substitute for the offline re-id assessment on real data.
**Patterns to follow:** existing `test_time_e2e.py` leak/k-anon assertions.
**Test scenarios:**
- Safety: leak assertions across all three artifact types pass.
- Safety: a `< k` per-column/per-device subgroup discloses no distribution.
- Safety: a `< k` minority format never reaches a disclosed artifact.
- Safety: per-subject intermediates do not appear in stdout/stderr/logs or any temp file.
- Safety: combining a column's disclosed distributions does not uniquely recover an injected outlier.
- Safety: birth/DOB and single-event date columns disclose no temporal facet.
**Verification:** the mechanical non-disclosure suite passes and fails loudly if any control is removed.

## System-Wide Impact

- **Interaction graph:** `profile_file` → `_attach_facets` (new facets) → `build`/`_render_md`
  (serialization) → `synthesize`/`build_synthetic_from_dictionary` (consumption). All three seams change.
- **Error propagation:** malformed/mixed timestamps must degrade to dominant-format + flag (R3),
  never raise during build.
- **State lifecycle risks:** per-subject grouping intermediates (Unit 2) must not persist — the core
  privacy risk; Unit 8 guards it.
- **API surface parity:** `synthesize()` is called from `build`, `add_layer_to_dictionary`, and
  `build_synthetic_from_dictionary` — the R17 rewrite and R18 sizing must hold across all three.
- **Unchanged invariants:** codebook raw-text path, categorical k-anon in `profile_column`, the
  `is_birth_name` suppression, and the `SYNTH_` id remapping are preserved, not altered.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Cohort distributions leak at ~37 subjects (tails/diurnal/coverage) | R11–R14 controls reuse `k`/`bin_min_count`; Unit 8 triangulation test; enrollment-relative coverage |
| Per-subject grouping intermediate persists a fingerprint | R16 ephemeral-collapse; explicit Unit 8 assertion |
| `synthesize()` rewrite breaks the 3 call sites / determinism | Unit 4 determinism test; parity check across build / add_layer / dict-only |
| Format template embeds a literal real value | R15 value-free-template validation + Unit 1/8 assertions |
| Statistical fidelity unverifiable in CI | Reframed to directional offline goal (deferred validation on the box), not a CI gate |
| "Runs unmodified" overclaim vs DST/dup/null pathologies | Explicit scope boundary; documented as residual hardening at the gate |
| k-anon not composable: ~6 k=5 releases per column across 4 device families sharing one ~37-subject pool can jointly narrow below k | Mechanical k=5 CI gate + **required** offline cross-column/cross-file re-id assessment before disclosure (resolved 2026-07-21; no in-code k-budget for now) |
| seed=0 gives one realized cohort → analyst code can pass on that single realization yet break on real data's different-but-valid structure (Goodhart) | Multi-seed exposure deferred (Open Questions); offline gated run on real data is the backstop |

## Documentation / Operational Notes

- The offline cohort-statistics comparison (directional success goal) runs where real TIME data
  lives — WARP box `root@10.0.0.62`, `/procedure/data/local_data` (IP drifts per session; re-point
  the `claude-science-vm` alias). Not part of CI.
- Update the `/jupyter` / dictionary handoff docs if the dictionary schema (new `format` /
  `temporal_distribution` fields) is surfaced to analysts.

## Sources & References

- **Origin document:** docs/brainstorms/synthetic-timestamp-fidelity-requirements.md
- Related code: `src/gated_cs/profiler/{profile,temporal,synthesize,build_dictionary,config,subject_key}.py`
- Related work: `is_birth_name` birth-month-leak fix (merged to `master`, PR #1)
