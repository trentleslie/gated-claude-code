---
date: 2026-11-13
topic: pre-rebuild-hardening
---

# Pre-rebuild Hardening: UUID Categories, Gate Rule Descriptions, Audit Log Preservation

## Problem Frame

Ash Fernando compared the gated Arivale box (a copy of this repo from about 2026-07-15) with `master` and recommended rebuilding the box from `master`. A source review of `master` at `02d25ac` confirmed the recommendation and found defects that the rebuild would carry forward:

1. **Real identifiers published as categories.** A categorical value is published in the dictionary, and reused in synthetic data, whenever at least k = 5 rows share it. The `coach` column in the Arivale `clients.tsv` holds staff UUIDs. Each UUID passes the rule and the column name matches no sensitive-name pattern, so real UUIDs reach the analyst.
2. **The gate's release rules are misdescribed.** The comment on `max_quasi_identifier_cols` in `src/gated_cs/config.py` says the quasi-identifier rule covers count-less tables. The gate applies it to tables with counts too. Verified on `master`: a one-way grouped count releases with 4 labelled groups and is quarantined with 5 or more; any second low-cardinality categorical column (a two-way crosstab) is quarantined. Operators reading the comment and runbook will misjudge the review load.
3. **Provisioning erases the audit log.** `provision/provision.sh` truncates `/var/gate/audit.jsonl` on every run. Re-provisioning a box with history destroys the only record of past release decisions, which is also the differencing monitor's only input.
4. **The differencing monitor never runs.** `gate-monitor` exists as a command, but nothing schedules it. Review showed that scheduling it as it stands would not work (see Key Decisions), so this document defers it.

Fixing 1 to 3 before Ash rebuilds means the new Arivale dictionary is built once, and the existing audit history survives.

## Requirements

**Identifier-valued categories**
- R1. A UUID-shaped value is never published as a category value in the dictionary or reused in synthetic data, whatever the column's name and whatever share of the column is UUID-shaped. This is a per-value guarantee.
- R2. "UUID-shaped" is defined once and covers: case-insensitive, hyphenated 8-4-4-4-12 form, bare 32 hex characters, and the same with braces or a `urn:uuid:` prefix.
- R3. In addition, a non-numeric column whose values are mostly UUID-shaped is treated as sensitive, using the same bar and sampling as the existing date-valued rule. Because the release gate reuses the profiler's sensitivity test, a submitted output table containing such a column is quarantined for human review. This is intended.
- R4. Non-disclosure tests prove no UUID appears in the dictionary JSON, the rendered dictionary text, or the synthetic sample, for delimited and Parquet inputs, across three fixtures: a pure `coach`-like column (each UUID shared by 5 or more rows, 50 or fewer distinct values), a mixed column where most values are a placeholder string, and a column whose first 200 rows contain no UUID.

**Gate rule descriptions**
- R5. The comment on `max_quasi_identifier_cols` matches the behaviour: the rule applies on both release paths.
- R6. The runbook's smoke-test guidance states the real release rule: a grouped count releases only with fewer than 5 distinct labelled groups and a single grouping column; 5 or more groups, or a second categorical column, go to human review.
- R7. The runbook states what the differencing monitor does and does not detect. It detects threshold probing. It does not detect subtraction across nested or overlapping releases that each pass on their own; that needs a manual check.

**Audit log preservation**
- R8. Provisioning never truncates an existing audit log. It creates the log only when absent.
- R9. The runbook tells the operator to archive the existing audit log to a data-owner-only location before retiring or rebuilding a box.

**Test baseline**
- R10. The stale assertion in `test_run_analysis_wrapper_pins_trusted_paths` is corrected. It expects `DATA_DIR=/data/arivale`, while the wrapper now carries a placeholder that provisioning fills in. The pinning itself is intact.

## Success Criteria

- Rebuilding a dictionary from each R4 fixture publishes zero UUIDs.
- No new test failures against the `master` baseline, and the wrapper-pinning test passes.
- An operator reading `config.py` and the runbook predicts correctly which of these release: a 4-group count (yes), an 8-group count (no), a two-way crosstab (no).
- Running provisioning twice on a box leaves earlier audit entries in place.

## Scope Boundaries

- **No scheduled monitor in this work.** Deferred to its own brainstorm; see Key Decisions.
- No detection of nested-cohort subtraction. It needs the gate to record which subjects contribute to each release, which changes the release hot path.
- No broader identifier-shape detection (hashes, prefixed codes, staff usernames). UUID only. The gap is covered for the Arivale rebuild by a one-time hand review of published category lists (Dependencies).
- No change to any gate release rule. Only descriptions.
- No change to time facets.
- Not deployed to any box by this work. Ash's rebuild picks it up from `master` and must wait for this to merge.

## Key Decisions

- **Arivale rebuild publishes time facets with upstream defaults** (Trent, 2026-11-13). Ash's hand audit of the new time facets and the offline re-identification assessment remain on his rebuild checklist. Reviewer note for that audit: the absolute min/max month per date column is set by the earliest and latest record, so it is not protected by the k = 5 rule the way the histograms are.
- **Per-value UUID filter, not only a column classifier.** A "mostly UUID" column rule misses a column that is 40% UUIDs and 60% a placeholder, and misses files where UUIDs start after the sampled rows. Those cases would publish exactly the values this fix exists to stop.
- **Monitor scheduling deferred.** The monitor re-reads the whole log on each run, so one flag fails every later run until the log is truncated. Routine quarantines (R6) are likely to trip its suppression-rate window. A missing log reports a pass, and a crash is indistinguishable from a flag. A failed system unit is also likely readable by the analyst account. Scheduling it needs an acknowledge mechanism, distinct outcomes, an operator-only signal, and thresholds calibrated on a real audit log. That is a design task, not a provisioning tweak.
- **One pull request.** With the monitor deferred, the remaining work is one small change set: UUID handling, description fixes, audit log preservation, one stale test assertion.

## Dependencies / Assumptions

- Ash's rebuild checklist gains three items outside this repo change: (a) review every published category list once, on the data-owner side, for identifier-like values before the dictionary reaches the analyst; (b) archive the old box's audit log; (c) run `gate-monitor` by hand from the new install over that archived log and record the result. Item (c) checks about four months of unmonitored history and supplies the calibration data the deferred monitor work needs.
- Baseline on `master` at `02d25ac`: 273 pass, 2 fail in the main checkout's environment. A reviewer's environment without `pyarrow` showed 38 failures, so the baseline is environment-dependent. The second failure, `test_exemplar_impute_produces_layer_and_finite_quality`, is not diagnosed here.

## Outstanding Questions

### Resolve Before Planning
- None blocking. Two owner decisions are open but do not change this change set; see below.

### Open owner decisions (do not block this work)
- [Gate policy] Is quarantining a one-way count with 5 or more labelled groups intended? It follows from treating any string column with 5 or more near-unique values as identifier-like. If not intended, it is a separate change to a release rule.
- [Exposure] The current box's dictionary and synthetic data already contain the `coach` staff UUIDs. Decide whether that needs any handling beyond retiring the old instance.

### Deferred to Planning
- [Affects R1][Technical] Where the per-value filter sits so that every published surface is covered by one check.
- [Affects R4][Technical] Whether a Parquet column with a native UUID or fixed-length binary type reaches the profiler in a form the shape test recognises.
- [Affects R10][Needs research] Cause of the `exemplar_impute` test failure and whether it belongs in this change.

## Next Steps
-> /ce:plan for structured implementation planning
