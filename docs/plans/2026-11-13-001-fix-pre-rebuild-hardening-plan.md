---
title: "fix: Pre-rebuild hardening (UUID categories, gate rule descriptions, audit log preservation)"
type: fix
status: completed
date: 2026-11-13
origin: docs/brainstorms/2026-11-13-pre-rebuild-hardening-requirements.md
---

# fix: Pre-rebuild hardening (UUID categories, gate rule descriptions, audit log preservation)

## Overview

One small pull request that must merge before the Arivale box is rebuilt from `master`. It stops UUID-shaped values from being published as dictionary categories, corrects the descriptions of the gate's release rules, stops provisioning from erasing the audit log, and fixes one stale test assertion.

This pull request also adds this plan, `docs/plans/2026-11-13-001-fix-pre-rebuild-hardening-plan.md`, and its origin document, `docs/brainstorms/2026-11-13-pre-rebuild-hardening-requirements.md`, to the repo; neither exists on `origin` before it.

## Problem Frame

See origin: `docs/brainstorms/2026-11-13-pre-rebuild-hardening-requirements.md`. The rebuild would otherwise republish real staff UUIDs (the `coach` column), wipe about four months of audit history, and leave operators with a wrong picture of what the gate releases.

## Requirements Trace

- R1. No UUID-shaped value is ever published as a category or reused in synthetic data (per-value guarantee).
- R2. One definition of "UUID-shaped": case-insensitive; hyphenated 8-4-4-4-12; bare 32 hex; either form with braces or a `urn:uuid:` prefix. Planning refinement: a value is withheld when it *contains* a UUID-shaped token (bounded so that longer hex strings such as SHA-256 digests do not match), which also covers padded, quoted, prefixed and multi-valued cells.
- R3. A mostly-UUID non-numeric column is sensitive (same bar and sampling as the date-valued rule); the gate therefore quarantines output tables containing one.
- R4. Non-disclosure tests over three fixtures (pure, mixed with placeholder, UUIDs after row 200), for delimited and Parquet inputs, checking dictionary JSON, rendered text and synthetic sample.
- R5. `max_quasi_identifier_cols` comment matches behaviour (both release paths).
- R6. Runbook states the real release rule (fewer than 5 labelled groups and one grouping column release; otherwise review).
- R7. Runbook states what the differencing monitor does and does not detect.
- R8. Provisioning never truncates an existing audit log.
- R9. Runbook tells the operator to archive the audit log before retiring or rebuilding a box.
- R10. Stale assertion in `test_run_analysis_wrapper_pins_trusted_paths` corrected.

## Scope Boundaries

- No change to any gate release rule or threshold, with two stated exceptions: the intended quarantine of output tables with a mostly-UUID column (R3), and the per-value UUID check at the gate (Unit 6, approved by the owner on 2026-11-13).
- No change to time facets.
- No broader identifier-shape detection (hashes, prefixed codes).
- No deployment to any box.

### Deferred to Separate Tasks

- Scheduling `gate-monitor` (acknowledge mechanism, distinct outcomes, operator-only signal, threshold calibration): its own brainstorm, after the monitor has been run by hand over the archived Arivale audit log.
- Nested-cohort subtraction detection: separate design; changes the release hot path.
- Whether quarantining one-way counts with 5 or more groups is intended: owner decision, separate change if not.
- Staff UUIDs already published by the current box (`coach` column): owner decision on handling beyond retiring the old instance.

## Context & Research

Research was done inline from the source at `02d25ac`; no research agents and no external research were used, because every touched area has a direct local pattern.

### Relevant Code and Patterns

- `src/gated_cs/profiler/sensitivity.py`: `is_sensitive` holds the name rule, the near-unique rule, and the date-valued rule (first 200 non-null values, at least 60% matching `_DATEVAL`). The UUID column rule mirrors the date-valued rule.
- `src/gated_cs/profiler/profile.py`: `profile_column` is the only place category values are selected for publication (`out["categories"]`, values with count at least `k`). The dictionary JSON, the rendered text in `build_dictionary.py`, and `synthesize._draw_values` all read from that list, so one filter there covers every published surface.
- `src/gated_cs/profiler/build_dictionary.py`: `_codebook_text` is a second path that emits raw values (codebook files without a subject key). It bypasses `profile_column`. The build also copies source text verbatim into the dictionary: `#` comment lines (`file_metadata`), `column_descriptions`, column names, and file relative paths. `synthetic_main` regenerates samples from an existing dictionary's `categories` without re-profiling.
- `src/gated_cs/gate/sdc.py`: `_per_person_verdict` reuses `is_sensitive`, which is how R3 reaches the release gate with no gate change.
- `src/gated_cs/config.py`: the `max_quasi_identifier_cols` comment.
- `provision/provision.sh` step 5: `: > /var/gate/audit.jsonl` runs unconditionally.
- `provision/RUNBOOK.md`: smoke-test table and isolation notes.
- `tests/profiler/test_nondisclosure.py`: the `fmt` fixture parametrises every control over CSV and Parquet and scans all artifacts for forbidden tokens. New UUID tests follow it.
- `tests/profiler/test_sensitivity.py`: unit tests for `is_sensitive`.
- `tests/test_bridge_files.py`: text assertions over files in `provision/`; the stale assertion and a new provisioning assertion live here.

### Institutional Learnings

- `docs/solutions/best-practices/synthetic-data-sdc-mechanical-nondisclosure-gate-2026-07-22.md`: disclosure controls are locked by mechanical tests that prove the control fires.
- `docs/solutions/best-practices/runbook-verification-commands-are-security-checks-2026-11-11.md` and `docs/solutions/documentation-gaps/verify-doc-claims-against-code-2026-10-26.md`: runbook statements about gate behaviour must be checked against the code. R6 wording was verified by running the gate (4 groups release; 5 and 8 are blocked; two-way crosstab blocked).

## Key Technical Decisions

- **Filter per value at the single emission point, and also classify the column.** The per-value filter in `profile_column` delivers R1 on its own. The column rule in `is_sensitive` is kept because it is what carries the protection to the release gate (R3) and marks the column `sensitive` in the dictionary so the analyst knows values are withheld.
- **Filtered UUID values are counted, not silently dropped.** When the per-value filter removes values from a column that is not sensitive, the profile records how many were withheld (same style as `rare_categories_suppressed`), so the dictionary stays honest about what it omits.
- **Apply the same per-value filter to `_codebook_text`.** It is the only other path that publishes raw values. Cost is one call; it closes the bypass.
- **One shared shape test, "contains a UUID token".** Defined once in `sensitivity.py` and imported wherever needed. It searches for a UUID-shaped token with hex boundaries on both sides, after normalising the value (16-byte binary values and UUID objects are rendered in canonical form first). Withholding a value that merely contains a UUID is the safe direction and removes the padded, quoted and compound-cell bypasses.
- **Fail-closed scan of the build's published output.** Category filtering covers category values, but comment lines, descriptions, column names and file names are also published. After writing its artifacts, the build scans the dictionary JSON, the rendered text and the synthetic samples for the shared pattern and fails with a message naming the file and field if anything matches. The same scan runs after dictionary-only synthesis, so an older dictionary cannot republish UUIDs. This is what makes R1 hold for every published surface, and it is the pre-release check the runbook names.
- **Create-if-absent for the audit log.** Ownership and mode are still enforced every run; only the truncation goes.
- **Stale test fixed by asserting the placeholder and the substitution.** The test should assert that the wrapper carries the provisioning placeholder and never reads the data path from environment or arguments, which is the property it was written to protect.

## Open Questions

### Resolved During Planning

- Where the per-value filter sits: `profile_column`, plus `_codebook_text`.
- Whether the wrapper-pinning failure is a real regression: no. The wrapper carries `DATA_DIR=__GATED_CS_DATA_DIR__`, baked in by provisioning; the test still expects `/data/arivale`.

### Deferred to Implementation

- Key name for the withheld-UUID count in a column profile. It counts distinct UUID-containing values that met k.
- Cause of the `test_exemplar_impute_produces_layer_and_finite_quality` failure. Diagnose only far enough to say whether it is environmental; fix only if trivial, otherwise report it in the pull request description.

## Implementation Units

- [x] **Unit 1: UUID shape test and column sensitivity rule**

**Goal:** Define "UUID-shaped" once and make a mostly-UUID column sensitive.

**Requirements:** R2, R3

**Dependencies:** None

**Files:**
- Modify: `src/gated_cs/profiler/sensitivity.py`
- Test: `tests/profiler/test_sensitivity.py`
- Test: `tests/gate/test_sdc.py`

**Approach:**
- Add the shared "contains a UUID token" predicate (see Key Technical Decisions), including normalisation of 16-byte binary values and UUID objects.
- In `is_sensitive`, alongside the date-valued check, flag a non-numeric column when the sampled share of UUID-shaped values meets the same bar the date rule uses.

**Execution note:** Test-first.

**Patterns to follow:**
- The `_DATEVAL` rule in `is_sensitive`.

**Test scenarios:**
- Happy path: each R2 form (lowercase hyphenated, uppercase hyphenated, bare 32 hex, braced, `urn:uuid:` prefixed) is UUID-shaped.
- Happy path: padded (leading or trailing space, trailing carriage return), quoted, prefixed (`coach:<uuid>`) and multi-valued (`<uuid>;<uuid>`) cells are detected.
- Happy path: a 16-byte binary value and a UUID object are detected.
- Edge case: not detected: 31 hex characters, a hyphenated string with a non-hex character, a 64-hex SHA-256 digest, an empty string, a missing value.
- Happy path: a column named `coach` with 10 distinct UUIDs each repeated 10 times is sensitive.
- Edge case: a column of ordinary categories (`A`, `B`, `C`) is not sensitive (no regression of `test_non_date_category_not_flagged`).
- Edge case: a column that is 40% UUIDs and 60% `unassigned` is not flagged by the column rule (documents the limit that Unit 2 covers).
- Integration: `check_table` on a count-bearing table grouped by a UUID-valued column with 4 groups returns a block verdict.

**Verification:**
- The sensitivity and SDC tests pass, including the pre-existing ones.

- [x] **Unit 2: Per-value filter on published categories and codebook text**

**Goal:** No UUID-shaped value reaches any published artifact, whatever the column verdict.

**Requirements:** R1, R4

**Dependencies:** Unit 1

**Files:**
- Modify: `src/gated_cs/profiler/profile.py`
- Modify: `src/gated_cs/profiler/build_dictionary.py`
- Test: `tests/profiler/test_nondisclosure.py`
- Test: `tests/profiler/test_profile.py`
- Test: `tests/profiler/test_parquet.py`
- Test: `tests/profiler/test_synthetic_from_dict.py`

**Approach:**
- In `profile_column`, exclude UUID-shaped values when building `categories` and record the number withheld.
- In `_codebook_text`, exclude UUID-shaped values and note the count in the existing "more" style.
- Add the fail-closed scan at the end of the build and at the end of dictionary-only synthesis (`synthetic_main`), over the dictionary JSON, the rendered text and the synthetic samples. The run manifest is excluded: it holds input hashes and package versions, not data values.

**Execution note:** Test-first; write the three failing non-disclosure fixtures before the filter.

**Patterns to follow:**
- `rare_categories_suppressed` in `profile_column`.
- The `fmt`-parametrised artifact scan in `tests/profiler/test_nondisclosure.py`.

**Test scenarios:**
- Integration (pure): a table with a subject key and a `coach` column of 10 UUIDs, each on 10 rows; build dictionary and synthetic sample; no UUID-shaped string appears in the dictionary JSON, the rendered text, or the synthetic sample. CSV and Parquet.
- Integration (mixed): same, but 60% of `coach` values are `unassigned`; the column is not sensitive, `unassigned` is published, no UUID is, and the withheld count equals the number of distinct UUIDs meeting k. CSV and Parquet.
- Integration (late start): first 200 rows hold `unassigned`, UUIDs follow; no UUID published. CSV and Parquet.
- Edge case: a column whose only k-passing values are UUIDs yields an empty category list and a withheld count, and synthesis still produces a column without error.
- Edge case: a codebook file (under a `raw` directory, name containing `questions`, no subject key) containing a UUID in one cell: the rendered codebook text omits it.
- Happy path: an ordinary categorical column is unchanged (no withheld count key).
- Integration (native Parquet): a Parquet column of fixed-length 16-byte binary UUIDs, each on 10 rows: no UUID in canonical or byte-repr form is published.
- Error path: a file with a UUID in a `#` comment line fails the build with a message naming the file and the field; same for a UUID used as a column name.
- Error path: dictionary-only synthesis from a hand-made dictionary whose `categories` contain a UUID fails closed and writes no sample containing it.
- Edge case: a build whose inputs contain no UUIDs passes the scan; SHA-256 digests in the run manifest do not trip it.

**Verification:**
- Using the existing `_artifacts` helper's three surfaces (dictionary JSON, rendered text, synthetic samples), the shared pattern finds nothing in any fixture, both formats, and each fixture's literal UUIDs are absent.

- [x] **Unit 3: Audit log preservation in provisioning**

**Goal:** Re-running provisioning leaves existing audit entries in place.

**Requirements:** R8

**Dependencies:** None

**Files:**
- Modify: `provision/provision.sh`
- Test: `tests/test_bridge_files.py`

**Approach:**
- Replace the truncation in step 5 with `touch` (creates if absent, never truncates); keep the `chown` and `chmod` lines unconditional.

**Patterns to follow:**
- Text assertions over `provision/provision.sh` in `tests/test_bridge_files.py` (for example `test_provision_installs_gate_venv_from_the_lock`).

**Test scenarios:**
- Happy path: `provision.sh` no longer contains the truncation of `/var/gate/audit.jsonl` and does contain the `touch`.
- Integration: the step-5 audit-log lines, run twice in a shell against a temporary path holding one prior entry, leave that entry in place.
- Happy path: `provision.sh` still sets owner `cs-exec:cs-exec` and mode `0600` on the audit log.

**Verification:**
- The bridge-file tests pass; reading step 5 shows an existing log is untouched and a missing log is created.

- [x] **Unit 4: Stale wrapper-pinning assertion**

**Goal:** The wrapper-pinning test asserts the property it protects and passes.

**Requirements:** R10

**Dependencies:** None

**Files:**
- Modify: `tests/test_bridge_files.py`

**Approach:**
- Assert the wrapper sets `DATA_DIR` from the provisioning placeholder, that `provision.sh` substitutes that placeholder, and that the wrapper does not read the data path from environment or arguments. Leave the other pinned-path assertions as they are.

**Test scenarios:**
- Happy path: `test_run_analysis_wrapper_pins_trusted_paths` passes against the current wrapper.
- Error path: the assertion would fail if `DATA_DIR` were taken from `$1` or an environment variable (reason this by inspection of the assertion; no mutation harness).

**Verification:**
- The test passes and still fails if the placeholder line is removed from the wrapper.

- [x] **Unit 5: Rule descriptions in config comment and runbook**

**Goal:** `config.py` and the runbook describe the gate as it behaves.

**Requirements:** R5, R6, R7, R9

**Dependencies:** Units 1 to 3 (so the runbook describes merged behaviour)

**Files:**
- Modify: `src/gated_cs/config.py`
- Modify: `provision/RUNBOOK.md`

**Approach:**
- Config comment: the quasi-identifier rule applies on both release paths; a count-bearing table with more than one low-cardinality categorical column is quarantined.
- Runbook smoke-test guidance: a grouped count releases with fewer than 5 labelled groups and one grouping column; 5 or more groups, a second categorical column, or a mostly-UUID column go to review. State the caveat that a grouping column whose name matches the sensitive-name patterns (for example `timepoint`, `visit_date`, anything ending `_id`) is quarantined at any group count.
- Runbook: a short section on `gate-monitor`: how to run it by hand, that it detects threshold probing, that it does not detect subtraction across nested or overlapping releases, and that it is not scheduled.
- Runbook: before retiring or re-provisioning a box, archive `/var/gate/audit.jsonl` to a data-owner-only location (owner-only mode, outside any path the analyst account or the bridge group can read); note that provisioning no longer truncates it.
- Runbook: after upgrading a box, rebuild the dictionary and synthetic samples before the analyst account sees them again; name the build's fail-closed UUID scan as the pre-release check.

**Test scenarios:**
- Test expectation: none -- comment and documentation only. Each behavioural sentence added to the runbook must be checked against the code or a gate run before it is written.

**Verification:**
- A reader of the two files predicts: 4-group count releases, 8-group count is quarantined, two-way crosstab is quarantined.

- [x] **Unit 6: Per-value UUID check at the release gate (approved by owner, 2026-11-13)**

**Goal:** A submitted output table that contains any UUID-shaped value in a non-count column is quarantined.

**Requirements:** Extends R3. This is a gate rule change, which the origin document excluded; it is listed here because review showed the column rule alone can be evaded.

**Dependencies:** Unit 1

**Files:**
- Modify: `src/gated_cs/gate/sdc.py`
- Test: `tests/gate/test_sdc.py`
- Test: `tests/gate/test_redteam.py`

**Approach:**
- In `check_table`, before either release path, block when any non-count column holds a value matching the shared predicate. Fail closed on error, as the per-person check does.
- Why: the analyst's script controls its own output. Grouping by `coach` and padding with placeholder rows keeps the UUID share under the column rule's bar and the group count under 5, so a table carrying real UUIDs would release.

**Test scenarios:**
- Error path: a 4-row count table with labels `<uuid>`, `<uuid>`, `x`, `y` and counts of 10 is blocked (released today).
- Error path: a count-less 3-row table with one UUID cell is blocked.
- Happy path: a 4-group count table with ordinary labels still releases.
- Integration: a red-team script that groups by a UUID-valued column and pads its output is quarantined end to end.

**Verification:**
- No table containing a UUID-shaped value reaches the results directory in any test.

## System-Wide Impact

- **Interaction graph:** `is_sensitive` is shared by the profiler and by `sdc._per_person_verdict`, so the column rule also changes release decisions: outputs grouped by a UUID-valued column now quarantine. `profile_column` is also used by the add-layer path in `build_dictionary.py`, which gains the per-value filter.
- **State lifecycle risks:** existing dictionaries are not rewritten; a box keeps publishing old values until its dictionary is rebuilt.
- **API surface parity:** the HTTP service in `src/gated_cs/service/api.py` runs the same gate and inherits the change.
- **Unchanged invariants:** thresholds in `config.py`, the k = 5 category rule, the quasi-identifier rule, time facets, the sandbox, and the audit record format are not changed.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| A legitimate non-identifier value happens to be 32 hex characters and is withheld | Accepted: withholding is the safe direction, and the withheld count makes it visible |
| Native Parquet UUID or binary columns bypass a string shape test | Normalised before the test; required fixture in Unit 2 |
| A script can still re-encode an identifier, or invent counts, to pass a small table through the gate | Out of scope; Unit 6 closes the accidental case only. Recorded in the runbook as a known limit and carried to the deferred monitor work |
| The build now fails on any UUID in comments, column names or file names | Intended fail-closed behaviour; the message names the file and field so the operator can decide |
| More quarantines raise review load and would raise the monitor's suppression rate | Documented in the runbook; monitor scheduling is deferred until calibrated |
| Rebuild happens before this merges | Ash is asked to hold the rebuild; the dependency is stated in the origin document |

## Premises

| kind | subject | expected | check |
|---|---|---|---|
| ref | `origin/master` of the repo | exists | `git rev-parse --verify origin/master` |
| path | `src/gated_cs/profiler/sensitivity.py` | exists | stat |
| path | `src/gated_cs/profiler/profile.py` | exists | stat |
| path | `src/gated_cs/profiler/build_dictionary.py` | exists | stat |
| path | `provision/provision.sh` | exists | stat |
| path | `provision/RUNBOOK.md` | exists | stat |
| path | `tests/profiler/test_nondisclosure.py` | exists | stat |
| path | `tests/test_bridge_files.py` | exists | stat |
| check | provisioning still truncates the audit log on `origin/master` | 1 | `git grep -c ': > /var/gate/audit.jsonl' origin/master -- provision/provision.sh \| cut -d: -f3` |
| check | wrapper still carries the data-dir placeholder on `origin/master` | 1 | `git grep -c 'DATA_DIR=__GATED_CS_DATA_DIR__' origin/master -- provision/run-analysis-wrapper \| cut -d: -f3` |

## Documentation / Operational Notes

- Pull request description should state: pre-existing test baseline, the result of the `exemplar_impute` diagnosis, and that the Arivale rebuild is waiting on this merge.
- Greptile review is warranted: the change carries disclosure-control logic.
- The Arivale rebuild checklist (owned by Ash) must include: (a) a data-owner hand review of every published category list for identifier-like values, since broader identifier detection is out of scope; (b) archiving the old box's audit log; (c) running `gate-monitor` by hand over that archived log and recording the result.
- Success gate: no new test failures against the `master` baseline (273 pass, 2 fail in the main checkout's environment), and `test_run_analysis_wrapper_pins_trusted_paths` passes.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-11-13-pre-rebuild-hardening-requirements.md](../brainstorms/2026-11-13-pre-rebuild-hardening-requirements.md)
- Related code: `src/gated_cs/profiler/sensitivity.py`, `src/gated_cs/profiler/profile.py`, `src/gated_cs/gate/sdc.py`, `provision/provision.sh`
