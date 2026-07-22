---
date: 2026-07-21
topic: synthetic-timestamp-fidelity
---

# Synthetic Timestamp Fidelity for the TIME Data Dictionary

## Problem Frame

The gated-cs profiler produces synthetic samples so a gated LLM analyst can develop
scripts that later run against the real wearable data behind the gate. Today
`synthesize()` renders every timestamp column as a random date-only string
(`20YY-MM-DD`, years 2015–2020), ignoring each device's real format and the temporal
structure of the data. An analyst who writes datetime parsing, timezone handling,
resampling, gap detection, or session segmentation against these samples writes code
that silently passes on synthetic data and breaks on real data — the exact failure the
synthetic samples exist to prevent.

Two facts constrain the fix:
- Synthetic samples are regenerated from the dictionary **alone** (no raw-data read, via
  `build_synthetic_from_dictionary`), so anything the synthesizer needs must be persisted
  into the dictionary as **non-disclosive** metadata.
- Each device has its **own** timestamp format (Oura ≠ Stelo-CGM ≠ Withings ≠ REDCap), so
  capture and rendering are per-column/per-file, never global.

```
 RAW (behind gate)          DICTIONARY (non-disclosive)         SYNTHETIC SAMPLE
 per-device timestamps  ->  R1–R3  format descriptor       ->   R7 rendered in device format
 per-subject timelines  ->  R4–R6  COHORT distributions    ->   R8 fresh synthetic subjects
                              (no real timeline stored)          drawn from distributions
        │                            │                                   │
        └── privacy boundary ────────┘  aggregates + k-anon, no raw rows │
                                        no per-subject temporal fingerprint
```

## Requirements

Terminology: **datetime column** = any column holding temporal data (R1/R7 apply to all).
**Longitudinal timestamp column** = the time-series subset that also receives temporal-
structure modeling (R4–R6, R8).

**Per-column format capture (profiler)**
- R1. For each datetime column, detect and record a non-disclosive format descriptor:
  representation (ISO-8601 string / epoch seconds / epoch millis / other), granularity
  (date-only vs date-time, sub-second precision), separator, timezone handling (UTC `Z` /
  fixed offset / naive-local), and the strftime-style pattern. Schema-level metadata only —
  no real values.
- R2. Format detection is per-column/per-file, so each device's distinct format is captured
  independently. There is no single global timestamp format.
- R3. When a column carries mixed or partially unparseable formats, capture the dominant
  format, **record each minority format present** (for R8 to render), and flag the column as
  mixed rather than failing the build.

**Cohort-level temporal-structure capture (profiler)**
- R4. For longitudinal timestamp columns, capture cohort-level *distributions* sufficient to
  regenerate realistic timelines: sampling cadence, wear/recording session-length
  distribution, inter-session gap-length distribution, diurnal (hour-of-day) activity
  pattern, and missing-day / coverage rate.
- R5. Only cohort-level aggregates are stored — never any individual subject's actual
  timeline, gap sequence, or per-subject temporal fingerprint. Captured distributions must
  clear the same non-disclosure / k-anon bar as the rest of the dictionary. R11–R16
  operationalize this bar (asserting it is not enough at ~37 subjects).
- R6. Carry forward the existing birth/DOB suppression: sensitive/suppressed date columns
  receive no temporal-coverage or temporal-distribution capture, so this cannot reintroduce
  the birth-month leak fixed in `is_birth_name`.

**Non-disclosure engineering (operationalizes R5; applies to R1–R5)**
- R11. Minimum-subgroup (k) gate: any distribution or format descriptor computed over a
  per-column/per-file subgroup smaller than the dictionary's `k` must be suppressed, merged
  into a coarser bucket, or omitted — never disclosed. (At ~37 subjects, per-device splits
  can drop well below k.)
- R12. Tail/extremes suppression: for every stored distribution, clip/winsorize min/max
  extremes or enforce a minimum count per bin (analogous to the categorical k-anon rule)
  before persisting — a single tail value can single out one subject.
- R13. Coarsen behavioral fingerprints: compute the diurnal pattern only at a granularity
  meeting k, in coarse blocks (e.g. 4-hour) rather than 24 discrete hours.
- R14. Enrollment-relative coverage: missing-day / coverage-rate is computed relative to each
  subject's own enrollment start (day-N-of-study), never anchored to absolute calendar dates,
  so nothing finer than the accepted month-level resolution is disclosed.
- R15. Format-descriptor safety: R1–R3 descriptors (including the mixed flag) clear the same
  k-anon bar; the derived template must be a fully generalized strftime/regex template with no
  digit sequences or literal substrings pulled from observed values, validated before persist.
- R16. Ephemeral intermediates + generalized guard: the per-subject grouping used to estimate
  distributions must collapse to aggregates in-memory and never persist (no per-subject
  timeline/gap sequence survives into any artifact); and the R6 suppression generalizes to any
  near-unique single-event date column, not only name-matched birth/DOB.

**Faithful synthesis (synthesizer)**
- R7. Render each datetime column in its captured format template (pattern, timezone,
  epoch-vs-string, granularity), reproducing the device-specific look.
- R8. Generate fresh, heterogeneous synthetic subjects by drawing each subject's temporal
  parameters from the captured cohort distributions — reproducing realistic cadence,
  sessions, gaps, nightly clustering, missing days, and variable session lengths across
  subjects — within the month-level coverage range captured in R4. Emit at least one synthetic
  row for **every** format recorded by R3 (dominant and each flagged minority format), so
  parsing/timezone code is exercised against all real formats.
- R9. Synthesis stays dictionary-only: everything the synthesizer needs is read from the
  dictionary; no raw-data read at synthesis time (preserves `build_synthetic_from_dictionary`
  parity).
- R10. Determinism preserved: same dictionary + seed → identical synthetic output (matches
  the current `seed=0` contract).
- R17 (generation model). `synthesize()` must generate each synthetic subject's rows
  **jointly** — subject-key, timestamp, and (where present) value emitted together so one
  subject owns a coherent, time-ordered timeline. This replaces the current column-independent
  i.i.d. model (`synthesize.py` draws the join key per row via `rng.choice(id_pool)` and each
  column separately), which would otherwise scatter a subject's timestamps across the cohort
  and make gap/session structure illusory.
- R18 (sample sizing). Synthetic sample sizing must yield enough rows per synthetic subject to
  exhibit the captured temporal structure. Reconcile the current fixed `n_rows=100` over a
  50-id pool (~2 rows/subject) by raising `n_rows` and/or emitting variable rows-per-subject.
- R19 (value co-location). Value columns are attached to the same synthetic subject and
  ordered timeline as the timestamps (values still drawn from their existing histograms/
  categories), so resampling and per-session aggregation produce non-empty, plausibly-shaped
  output. No value-vs-time *waveform or correlation* modeling — only co-location. Nearly free
  given R17's joint per-subject row generation.

## Success Criteria
- A script's timestamp handling — parsing, timezone conversion, resampling, and gap/session
  detection — runs against synthetic samples without format- or structure-induced errors, and
  the same handling runs unmodified against real data behind the gate. (Breakage from
  *non-timestamp* columns — value ranges, categorical levels, null patterns — is out of scope
  for this change; see Scope Boundaries.)
- Per device, synthetic timestamp columns match the captured format template (pattern,
  timezone, granularity).
- Cohort-level temporal statistics of the synthetic data are directionally representative of
  the real cohort — a **design goal validated by a one-time offline gated comparison, not a CI
  hard gate** (real data cannot enter CI) — while no real subject's timeline is recoverable.
- A triangulation/linkage check confirms that combining all newly-disclosed distributions for
  a column does not narrow to a single real subject.
- Existing leak/k-anon tests still pass: no raw values, no per-subject timeline, no birth
  month in `dictionary.json` / `dictionary.md` / `synthetic_samples/`.

## Scope Boundaries
- No per-subject 1:1 fidelity — synthetic subjects are fresh draws from cohort distributions,
  not real-subject copies.
- No cross-file temporal alignment (a synthetic subject's Oura and CGM timelines need not
  correlate) unless it falls out for free — deferred.
- Not a general-purpose time-series simulator; scoped to what makes analyst timestamp code run.
- **Not all real-data timestamp pathologies are reproduced.** DST transitions, mid-record
  timezone-offset changes, duplicate/out-of-order timestamps, clock drift, and malformed/null
  timestamps are not guaranteed in synthetic samples; scripts may still need hardening for
  these at the gate. This bounds the "runs unmodified" claim above.
- Value↔timestamp *co-location* is in scope (R19); value-vs-time *waveform/correlation*
  modeling is not.

## Key Decisions
- **Full statistical fidelity via cohort distributions, not per-subject params.** Reconciles
  the requested realism (gaps, nightly clusters, missing days, variable session lengths) with
  the project's non-disclosure guarantee by sampling fresh subjects from cohort-level
  distributions.
- **Per-device / per-column format capture.** Devices differ; a global format would be wrong
  for most files.
- **Persist descriptors into the dictionary.** Synthesis is dictionary-only by contract, so
  format + distribution descriptors must live in the dictionary (and therefore be
  non-disclosive by construction).
- **Simpler baseline recorded as fallback.** A format + cadence + gap/session-length baseline
  (dropping diurnal and missing-day modeling) was considered and deliberately rejected in
  favor of full fidelity; it is retained as a documented fallback if the distributional work
  proves costly relative to the script-portability goal it serves.
- **Value↔timestamp co-location, not correlation (R19).** Value rows ride the same synthetic
  subject/timeline so resampling and session-aggregation scripts produce meaningful output;
  values stay drawn from existing histograms. Resolved 2026-07-21.
- **Success = format/structure correctness; statistical fidelity is directional.** The
  acceptance gate is timestamp parsing/tz/resampling/gap-session correctness + leak/k-anon;
  cohort-statistical fidelity is validated by a one-time offline gated comparison, not a CI
  hard gate. Resolved 2026-07-21.

## Alternatives Considered
- **Gate-time non-disclosive validation feedback.** Rather than (or alongside) richer
  synthesis, a gated dry-run could report schema/format-mismatch error *classes* back to the
  analyst — column-type-agnostic and reusable, catching breakage synthesis can never fully
  enumerate. Deferred as a possible complement, not part of this scope.

## Dependencies / Assumptions
- Builds on existing `temporal.py` facets (`cadence_label`, `month_bounds`) and the
  birth/DOB suppression guard (`is_birth_name`) just merged to `master`.
- Relies on the existing subject/join-key detection to group timestamps per subject when
  *estimating* cohort session/gap distributions (grouping is used to compute aggregates, not
  to store per-subject output).

## Outstanding Questions

### Deferred to Planning
- [Affects R4/R8][Technical] Representation of the temporal model: named parametric
  distributions vs empirical bucketed inter-arrival / hour-of-day histograms — which best
  balances legibility, non-disclosure, and fidelity.
- [Affects R11–R16][Technical] Concrete non-disclosure parameters: the `k` value, the
  tail/min-max/min-count-per-bin suppression rule, and the diurnal block width that make the
  distributions provably non-disclosive at ~37 subjects.
- [Affects R1/R3/R15][Technical] Exact format-descriptor schema and detection heuristics
  (epoch detection, sub-second precision, mixed-format handling, template-generalization
  validation).
- [Affects R4/R8][Technical] Whether diurnal/session modeling needs per-source archetypes
  (CGM continuous 24/7 vs Oura nightly sessions) or one adaptive model driven purely by the
  captured stats.
- [Affects R10][Technical] Whether to expose multiple seeds so analysts don't overfit to a
  single realized synthetic cohort (a pinned seed=0 yields one fixed draw forever).
- [Affects Success Criteria][Needs research] How to run the offline cohort-stat comparison
  (synthetic-from-synthetic round-trip, or a synthetic-raw fixture with known structure) given
  no real-data dependency in CI.

## Next Steps
-> /ce:plan for structured implementation planning
