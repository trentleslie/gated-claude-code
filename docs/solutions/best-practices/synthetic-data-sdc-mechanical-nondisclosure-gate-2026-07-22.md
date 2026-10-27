---
title: "SDC invariants belong in a mechanical CI non-disclosure gate — but a green gate is not a re-identification proof"
date: 2026-07-22
last_updated: 2026-07-22
category: best-practices
module: gated_cs.profiler
problem_type: best_practice
component: testing_framework
severity: high
applies_when:
  - Building a code-to-data / PHI-safe pipeline where analysts run code against synthetic samples that stand in for real cohort data
  - Adding a new disclosive facet (format descriptor, distribution, aggregate) to a profiler whose synthetic samples regenerate from the published artifact alone
  - Deciding what "validated" means before a data dictionary is disclosed behind a gate
tags: [sdc, non-disclosure, synthetic-data, k-anonymity, triangulation, ci-gate, gated-claude, time-cohort, timestamp-fidelity, release-blocker]
related_components: [profiler, build_dictionary, synthesize, format_detect, temporal_dist]
---

# SDC invariants belong in a mechanical CI non-disclosure gate — but a green gate is not a re-identification proof

Reference: PR [#4 — feat(profiler): synthetic timestamp fidelity with SDC controls](https://github.com/trentleslie/gated-claude-code/pull/4)
(branch `feat/synthetic-timestamp-fidelity`, +1666/-23 across 14 files), and its follow-up PR
[#5 — offline re-id gate fixes](https://github.com/trentleslie/gated-claude-code/pull/5), which
**built and ran** the offline gate this doc originally listed as deferred — and it immediately caught
15 real re-identification leaks that PR #4's CI gate and an LLM code review had both passed clean.

> **2026-07-22 update:** the caveat below (a green CI gate is not a re-id proof) is no longer
> hypothetical. The offline gate found 15 subject-level leaks on the real cohort — see
> "Why This Matters" and the new best practice in "Guidance."

## Context

The gated-CS profiler exists so an analyst can write timestamp-handling code (parsing, tz,
resampling, gap/session detection) against **synthetic samples behind the gate**, and have that code
actually run unmodified on the real TIME wearable cohort (Oura/Whoop/Stelo-CGM/Withings/REDCap,
~37 subjects). Before this run, `synthesize()` rendered every timestamp as a random date-only string
(`20YY-MM-DD`), so analyst code passed on the samples and broke on real data — the exact failure the
gate is meant to prevent.

This run taught the profiler to (a) capture a **value-free per-column timestamp format descriptor**
(`format_detect.py`), (b) capture **k-gated, tail-clipped, coarsened, enrollment-relative cohort
temporal distributions** (`temporal_dist.py`), and (c) render **joint per-subject timelines** in the
captured format (`synthesize.py`), all persisted into `dictionary.json` so
`build_synthetic_from_dictionary` can regenerate from the dictionary alone.

The load-bearing structural fact: **synthetic samples regenerate from the dictionary alone**, so
every new descriptor must be non-disclosive *by construction*, not by a downstream filter. That is
what makes the disclosure-control tests the real deliverable of the run, not the fidelity feature.

## Guidance

Encode the statistical-disclosure-control (SDC) invariants as an **adversarial CI gate** whose
fixture injects a single known outlier that is unique along *every* axis an attacker could exploit,
then assert the outlier cannot be recovered from any published artifact. In this run that gate is
`tests/profiler/test_nondisclosure.py` (Unit 8), and it locks five classes of control as CI release
blockers:

1. **Leak-free across every artifact, together.** Concatenate `dictionary.json` + `dictionary.md` +
   all `synthetic_samples/**/*.csv` into one blob and assert no real subject id and no raw
   birth date / birth *month* appears anywhere. Check the union, because a value suppressed in one
   artifact can still surface in another.
2. **A `<k` minority format is never disclosed** — not in the descriptor's `template`/`minority`
   list, and not rendered into any synthetic row (`assert not re.search(r"\.\d{6}", synth)`). The
   outlier's unique sub-second format must vanish from both the schema and the data.
3. **`<k` subgroups and single-event / birth columns emit no distribution at all.** A DOB column
   carries neither `temporal_coverage` nor `temporal_distribution`; a single-event enroll date
   captures no distribution (R16). Absence is the control — the safe output is *nothing*.
4. **Per-subject intermediates never persist.** Capture stdout+stderr during `build()` and assert no
   subject id / raw stamp was logged, *and* allowlist the top level of `out_dir`
   (`{dictionary.json, dictionary.md, run_manifest.json, synthetic_samples}`) so a stray intermediate
   file fails the test, *and* byte-scan every file under `out_dir` for the outlier token.
5. **Triangulation smoke: disclosed aggregates cannot narrow to one subject.** Combining every
   disclosed distribution for a column must keep `n_contributors >= k`, every histogram bin gated by
   **distinct-subject count** (see the added best practice below), and the coarsened diurnal block the
   outlier lives in stays a small share (`diurnal_blocks["00-04"] < 0.5`) rather than a solo 1-subject
   spike.

The fixture design is the technique worth copying: one `_OUTLIER_SUBJECT` with (a) a unique
`.%f` sub-second **format**, (b) a lone 3am **diurnal slot**, and (c) an extreme value (`hr=200`),
so a single test subject probes format-leak, temporal-triangulation, and value-leak at once.

**Added by PR #5 — gate disclosed aggregates by DISTINCT-SUBJECT count, not event count.** The
histogram bins (session-length, gap, coverage) in `_clip_hist` (`temporal_dist.py`) were originally
gated only by `bin_min_count` (≥5 *events* per bin). That is not a k-anonymity gate: one subject with
many sessions emits many events, so a bin can clear ≥5 events while representing only 1–4 distinct
people. The offline gate found 15 such bins on the real cohort — one backed by a **single** subject,
disclosing that person's timing pattern. The fix carries `(value, subject_id)` pairs through
`_clip_hist` and requires each bin to clear **both** `count >= bin_min_count` **and**
`n_distinct_subjects >= k`, attaching `n_subjects` to the disclosed record for audit. A distinct-
subject gate already protected the diurnal blocks; the histograms were simply *missed* — the lesson is
that a per-element privacy control must be applied to **every** disclosed element, or the weakest
unguarded one defines your real exposure. Anonymity is measured in *people*, not *rows*.

## Why This Matters

The tests verify the controls **FIRE on synthetic-raw fixtures** — that k-anon, tail suppression,
coarsening, format `<k` suppression, ephemerality, and triangulation resistance are all mechanically
enforced and will block a release if a future change regresses them. Because synthetic samples
regenerate from the dictionary, an un-gated disclosive facet would leak silently and permanently once
published; a red CI gate is the only thing standing between "added a nice fidelity feature" and
"published a re-identifiable timeline."

**The caveat is equally load-bearing and must travel with the gate:** a green Unit 8 is **not** the
re-identification proof. It runs on synthetic fixtures only. The actual release blocker for disclosure
is the offline gated assessment — run where the real TIME data lives (WARP box,
`/procedure/data/local_data`), doing cross-column *and* cross-file triangulation over the real
~37-subject pool, which a synthetic-fixture CI can never cover. Treat the mechanical gate as
"the controls are wired and can't silently regress," and the offline re-id assessment as
"the real cohort passes the implemented per-element checks." Conflating the two is the trap. Even the
offline pass is not proof against combined disclosure: it counts contributors per disclosed element and
tallies sole contributors across files, but never intersects contributor sets, so two elements with
five contributors each that share only one person go undetected.

**This is no longer hypothetical — it is the strongest evidence in this doc.** The offline gate
(`scripts/offline_reid_assess.py`), run on the real cohort, found **15 re-identification leaks that
CI's Unit 8 gate and a Greptile LLM review had both reported clean** — because both only ever touched
synthetic fixtures, and re-id risk is a property of the *real* distribution. Green automated checks on
the wrong substrate are worse than an obvious failure: they suppress scrutiny exactly where a real
person's behavioral fingerprint was leaking. The generalizable rule: **re-identification risk lives in
the real data, so it must be measured on the real data — a distinct offline gate on the secured box,
whose own report emits aggregate counts only (never a subject id, raw value, or timestamp) so the
safety check does not become its own leak.**

## When to Apply

- Any profiler/synthesizer where the published artifact is the sole input to sample regeneration
  (non-disclosure must hold by construction).
- Whenever you add a facet that summarizes real data (a new distribution, descriptor, or aggregate) —
  add the matching adversarial assertion in the same PR, using an injected outlier fixture.
- Before signing off a data dictionary for disclosure: confirm both the mechanical CI gate is green
  **and** the offline real-cohort re-id assessment has been run. Neither substitutes for the other.

## Examples

Absence-as-control assertion (birth + single-event columns emit no temporal facets):

```python
cols = d["files"][os.path.join("redcap", "TIME_demographics.csv")]["columns"]
assert "temporal_coverage" not in cols["date_of_birth"]      # birth quasi-identifier
assert "temporal_distribution" not in cols["date_of_birth"]
assert "temporal_distribution" not in cols["enroll_date"]    # single-event guard (R16)
```

Triangulation-resistance assertion (no disclosed aggregate narrows to one subject):

```python
td = d["files"][".../TIME_oura_hr.csv"]["columns"]["timestamp"]["temporal_distribution"]
assert td["n_contributors"] >= DEFAULTS.k
for hist_key in ("session_minutes", "gap_hours", "coverage_days"):
    for b in td[hist_key]:
        assert b["count"] >= DEFAULTS.bin_min_count
        assert b["n_subjects"] >= DEFAULTS.k   # one heavy subject can fill a bin on its own
assert td["diurnal_blocks"].get("00-04", 0.0) < 0.5   # outlier's 3am slot stays diluted
```

Ephemerality via out_dir allowlist (a stray intermediate file fails the test):

```python
expected_top = {"dictionary.json", "dictionary.md", "run_manifest.json", "synthetic_samples"}
assert set(os.listdir(out)) <= expected_top, "unexpected intermediate written to out_dir"
```

Distinct-subject bin gate (PR #5) — the fix that closed the 15 leaks. The signature had to change from
a values array to `(value, subject_id)` pairs precisely so the subject gate is *possible*:

```python
# BEFORE (leaky): counts events; one prolific subject can fill a bin alone.
if count >= thresholds.bin_min_count:
    out.append({"lo": lo, "hi": hi, "count": count})

# AFTER (fixed): require BOTH an event floor AND a distinct-subject floor.
count = int(sel.sum())
nsub  = int(pd.unique(sids[sel]).size)                 # distinct subjects in this bin
if count >= thresholds.bin_min_count and nsub >= thresholds.k:
    out.append({"lo": lo, "hi": hi, "count": count, "n_subjects": nsub})
```

The offline gate — the check CI cannot do — recomputes distinct-subject support per disclosed element
from the *real* data and flags any `< k` (`scripts/offline_reid_assess.py`):

```python
# for each disclosed [lo, hi) bin: count distinct REAL subjects contributing; flag if < k
subs = {sid for sid, vals in values_by_subject.items() if any(lo <= v < hi for v in vals)}
if len(subs) < K:
    leaks.append({"element": "hist_bin", "lo": lo, "hi": hi, "n_subjects": len(subs)})
```

It applies the same test to every disclosed element (format descriptor, diurnal block, each bin), plus
a cross-file sole-contributor check, and its report is aggregate counts only. Regression locked in by
`test_histogram_bin_requires_k_distinct_subjects` in `tests/profiler/test_temporal_dist.py`.

Reuse existing thresholds rather than inventing new ones: `k` (from `config.Thresholds`) gates both
the `<k` subgroup suppression and the triangulation contributor floor; `bin_min_count` gates both
histogram-bin and tail suppression. One knob, consistently applied across format, distribution, and
triangulation controls, keeps the guarantee legible.

## Related

- PR #4: https://github.com/trentleslie/gated-claude-code/pull/4 (the mechanical CI gate)
- PR #5: https://github.com/trentleslie/gated-claude-code/pull/5 (subject-count bin gate + the built offline gate)
- Plan: `docs/plans/2026-07-21-001-feat-synthetic-timestamp-fidelity-plan.md` (requirements trace R1–R19)
- Origin brainstorm: `docs/brainstorms/synthetic-timestamp-fidelity-requirements.md`
- **Implemented** offline re-id gate: `scripts/offline_reid_assess.py` + `scripts/box_rebuild_assess.sh`
  — run on the WARP box (`claude-science-vm`, `/procedure/data/local_data`); cross-column and cross-file
  triangulation over the real cohort. This is the concrete realization of what this doc originally
  called the "deferred" release blocker.
- Bin-gate fix: `src/gated_cs/profiler/temporal_dist.py` (`_clip_hist`).
