---
title: "A value-shape disclosure control must cover every publish path, every dtype, and every 'could not check' case"
date: 2026-11-13
category: best-practices
module: gated_cs.profiler
problem_type: best_practice
component: service_object
severity: high
applies_when:
  - Adding a rule that keeps a class of value (UUIDs, hashes, staff codes) out of the dictionary, synthetic samples or released tables
  - Adding or changing any function that writes dictionary.json, dictionary.md or synthetic_samples
  - Writing a per-value check with Series.map on columns that can arrive as categorical (Parquet dictionary-encoded columns)
  - Writing a scan whose clean result is read as "safe to publish"
  - Changing provision.sh steps that touch state a box accumulates over its life (the audit log)
symptoms:
  - "Categorical values with count >= k were published even when they were real staff UUIDs (Arivale clients.tsv coach column)"
  - "TypeError: 'Categorical' with dtype category does not support operation 'any' (or 'mean') from is_sensitive on a Parquet column"
  - "Derived layers were added to the published dictionary and samples without the new UUID scan"
  - "A sample directory the scan could not list was skipped and the scan still reported clean"
  - "provision.sh truncated /var/gate/audit.jsonl on every run"
root_cause: missing_validation
resolution_type: code_fix
related_components: [tooling, testing_framework, development_workflow, documentation]
tags: [uuid, non-disclosure, fail-closed, publish-paths, pandas-categorical, audit-log, greptile, sdc]
---

# A value-shape disclosure control must cover every publish path, every dtype, and every "could not check" case

## Context

PR [#25](https://github.com/trentleslie/gated-claude-code/pull/25) (`fix/pre-rebuild-hardening`, 7 commits,
head `2fb4217`, base `master` at `02d25ac`) hardened the repo before the Arivale box is rebuilt from
`master`. It merged on 2026-11-14 as `b92c373`. Requirements and plan are in the PR:
`docs/brainstorms/2026-11-13-pre-rebuild-hardening-requirements.md` and
`docs/plans/2026-11-13-001-fix-pre-rebuild-hardening-plan.md`.

The defect that started it: a categorical value is published in the dictionary, and reused in synthetic
data, whenever at least k = 5 rows share it. The `coach` column in the Arivale `clients.tsv` holds staff
UUIDs. Each UUID passes the k rule and the column name matches no sensitive-name pattern, so real
identifiers reached the analyst.

### What was built

| Area | Change |
|------|--------|
| `src/gated_cs/profiler/sensitivity.py` | One definition of "UUID-shaped" (`UUID_TOKEN`, `contains_uuid`, `uuid_mask`, `as_text`, `uuid_text`). A value matches when it *contains* a UUID token; bare 32-hex needs non-hex boundaries so SHA-256 digests do not match; 16-byte binary and `uuid.UUID` objects are rendered canonically first. `is_sensitive` flags a mostly-UUID column (first 200 non-null values, 60% bar, same as the date rule). |
| `src/gated_cs/profiler/profile.py` | `profile_column` drops UUID-shaped values from `categories` whatever the column verdict, and records `uuid_categories_withheld`. |
| `src/gated_cs/profiler/build_dictionary.py` | `_codebook_text` applies the same filter. `build()` reads its artifacts back from disk and scans dictionary JSON (keys included), rendered markdown and every file under `synthetic_samples`; on a finding it removes this run's artifacts and raises `PublishedUUIDError`. `build_synthetic_from_dictionary` refuses an older dictionary that holds UUIDs. `add_layer_to_dictionary` runs the same checks before writing anything. |
| `src/gated_cs/gate/sdc.py`, `run_analysis.py` | `_uuid_verdict` quarantines any output table with a UUID-shaped value or column name, before either release path. A rejected derived-layer dictionary update is audited as `dictionary_update_rejected`. |
| `provision/provision.sh` | `: > /var/gate/audit.jsonl` became `touch /var/gate/audit.jsonl`. Ownership and mode are still enforced every run. |
| `src/gated_cs/config.py`, `provision/RUNBOOK.md` | Descriptions now match gate behaviour, verified by running the gate: fewer than 5 labelled groups with one grouping column release; 5 or more groups, a second categorical column, or any UUID-shaped value go to review. |
| Tests | Two stale assertions corrected (`tests/test_bridge_files.py`, `tests/gate/test_exemplar_impute.py`). New tests in `tests/gate/` and `tests/profiler/`, including `tests/profiler/test_add_layer.py`. |

Test run on head `2fb4217` (2026-11-14, pandas 3.0.3, main checkout's `.venv`): 339 passed, 1 failed. The
failure was `test_exemplar_impute_produces_layer_and_finite_quality`, which shells out to `.venv/bin/python`
inside the worktree it runs from; the worktree used for this run had no `.venv`, so the failure is
environmental there. It was not re-run in a worktree with its own `.venv`.

### What validation caught after the planned units were done

The plan's six units landed in the first four commits. Three further commits fixed defects the plan had
missed. Each one was a gap in coverage, not in the rule itself.

1. **Categorical columns crashed the check** (`38cd196`). `Series.map` on a categorical column returns a
   `Categorical` when the mapping is one-to-one over the categories. That happens for a single-category
   column, and for a column with exactly one UUID category and one non-UUID category. A `Categorical`
   supports neither `any()` nor `mean()`. `is_sensitive` raised `TypeError` on such Parquet columns, and the
   published-sample scan reported them as unreadable. Reproduced on pandas 3.0.3: two categories mapping to
   `True`/`False` give a `Categorical`; three categories mapping to `True`/`False`/`False` give a plain bool
   array. The bug therefore depends on the data, and a fixture with three or more categories never shows it.
2. **A publish path the scan did not cover** (Greptile P1, fixed in `c3f0b7d`). `add_layer_to_dictionary()`
   is called by `run()` after a derivation and writes the layer's name and column names into both
   dictionary files and a sample. A pivot keyed on staff UUIDs puts the UUIDs in the header. The plan had
   named `profile_column` as "the only place category values are selected for publication", which is true
   for category *values* and false for column *names*.
3. **The scan passed what it could not read** (Greptile P2, fixed in `c3f0b7d`). `os.walk()` skips a
   directory it cannot list unless given `onerror`. An older subtree owned by another account would be
   skipped and the scan would report clean.
4. **Review pass on those fixes** (`2fb4217`). `os.walk` lists a symlinked directory but never descends into
   it, so symlinked sample directories are now reported as unchecked. `add_layer_to_dictionary` opened
   `dictionary.json` for writing before serializing, so an encoding error would have left a truncated
   dictionary; it now serializes first.

Greptile scored the PR 3/5 at commit `38cd196` with those two findings. Commits `c3f0b7d` and `2fb4217` came
after that review. Greptile re-reviewed head `2fb4217` at 5/5 on 2026-11-14, and the PR merged to `master`
as `b92c373` the same day.

## Guidance

1. **List the publish paths by grepping for writers, not by reasoning about the main path.** Before
   declaring a non-disclosure rule complete, find every function that writes `dictionary.json`,
   `dictionary.md` or anything under `synthetic_samples`, and every caller. In this repo that is `build()`,
   `add_layer_to_dictionary()` (reached from the gate's `run()`), `build_synthetic_from_dictionary()` and
   `_codebook_text()`. A filter at "the single emission point" covers only the values that pass through it.
2. **A value rule also applies to names.** Column names, layer names, file paths, comment lines and
   descriptions are copied from the source verbatim. A pivot turns values into column names. Scan keys and
   headers, not only cells.
3. **Check before writing when you can; scan after writing when you must.** `add_layer_to_dictionary` builds
   the JSON text, the markdown and the sample in memory, checks all three, then writes. `build()` writes
   many files in a loop, so it reads them back and removes this run's artifacts on a finding. Either way,
   serialize before opening the destination for writing.
4. **"Could not check" is a finding.** An unreadable file, an unlistable directory, a symlinked directory
   and an exception inside the check all fail the build or quarantine the table. Give `os.walk` an `onerror`
   handler and test `os.path.islink` on each directory it lists.
5. **Route every per-value check on a Series through one helper that casts to object first.**
   ```python
   def uuid_mask(series):
       return series.astype(object).map(contains_uuid).astype(bool)
   ```
   Never call `.any()` or `.mean()` on the direct result of `Series.map` when the column may be categorical.
6. **Give the gate its own per-value check.** The analyst's script controls its output. Grouping by a UUID
   column and padding with placeholder rows keeps the UUID share under the column bar and the group count
   under k, so a column classifier alone would release real identifiers.
7. **Error messages and audit reasons name the location, never the value.** `_redact` replaces UUID tokens
   in paths and keys, and the gate reports the column by position.
8. **Provisioning must be safe to run twice.** Create accumulated state only when absent. Test it by running
   the script's own creation step against a file that already has content.

## Why This Matters

The rule was right from the first commit and the PR would still have published staff UUIDs through derived
layers. On a disclosure path, the cost of a missed writer is the same as having no rule. The categorical
crash is the opposite failure: the check existed and fell over on a dtype the tests had not fed it, in a way
that only some data triggers. Truncating the audit log on re-provisioning would have destroyed about four
months of release decisions, which is also the differencing monitor's only input.

## When to Apply

- Any new "never publish values that look like X" rule (the plan defers hashes, prefixed codes and staff
  usernames; they will need the same treatment).
- Any new writer of dictionary or sample files, or any new caller of an existing one.
- Any pandas check that maps a predicate over a column read from Parquet.
- Any scan whose empty result gates a release or a publish step.

## Examples

Before, in `add_layer_to_dictionary` (truncates first, never scans):

```python
with open(dict_path, "w") as f: json.dump(d, f, indent=2)
with open(os.path.join(os.path.dirname(dict_path), "dictionary.md"), "w") as f:
    f.write(_render_md(d))
```

After (serialize, check, then write):

```python
text = json.dumps(d, indent=2)
findings = _dictionary_findings({k: v for k, v in json.loads(text).items() if k != "sources"})
findings += _text_findings(md, "dictionary.md")
findings += _frame_findings(synth, _redact(os.path.join("synthetic_samples", sample)))
if findings:
    _fail_closed(findings, [])
with open(dict_path, "w") as f: f.write(text)
```

Fixtures that would have caught the categorical crash, now in `tests/profiler/test_sensitivity.py`: a
single-category categorical column, and a categorical column with one UUID category and one non-UUID
category.

Provisioning, before and after:

```bash
: > /var/gate/audit.jsonl        # before: wipes the log on every run
touch /var/gate/audit.jsonl      # after: create if absent, never truncate
```

## Related

- PR [#25](https://github.com/trentleslie/gated-claude-code/pull/25): the change this documents.
- `docs/solutions/best-practices/parquet-input-format-disclosure-controlled-profiler-2026-10-26.md`: same
  lesson for readers ("route every reader"); this doc is the writer-side counterpart. Moderate overlap; a
  consolidation review is reasonable now that #25 has merged.
- `docs/solutions/best-practices/synthetic-data-sdc-mechanical-nondisclosure-gate-2026-07-22.md`: disclosure
  controls are locked by mechanical tests that prove the control fires.
- `docs/solutions/best-practices/runbook-verification-commands-are-security-checks-2026-11-11.md` and
  `docs/solutions/documentation-gaps/verify-doc-claims-against-code-2026-10-26.md`: fail closed, and check
  documented gate behaviour against the code.
- Still open and out of scope for #25: scheduling `gate-monitor`, nested-cohort subtraction, whether
  quarantining one-way counts with 5 or more groups is intended, and the staff UUIDs the current box has
  already published.
