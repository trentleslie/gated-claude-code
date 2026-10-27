---
title: "Adding an input format to the disclosure-controlled profiler: route every reader, round-trip dtypes, fail closed on nested types"
date: 2026-10-26
last_updated: 2026-10-26
category: best-practices
module: gated_cs.profiler
problem_type: best_practice
component: service_object
severity: high
applies_when:
  - Adding a new input file format (parquet, feather, xlsx, ...) to the profiler -> dictionary -> synthetic pipeline
  - Refactoring how raw data files are read, anywhere in src/ or scripts/
  - Synthetic samples must keep source dtypes so code written on them runs unchanged on real data
  - Acting on automated review (Greptile) findings on a disclosure-sensitive path
  - Adding a runtime dependency that the gate or the re-id check imports
related_components: [tooling, testing_framework, development_workflow]
tags: [parquet, input-formats, dtype-round-trip, synthetic-data, sdc, fail-closed, review-verification, deploy-drift]
---

# Adding an input format to the disclosure-controlled profiler: route every reader, round-trip dtypes, fail closed on nested types

## Context

A collaborator onboarding a new dataset asked whether filenames, headers and column dtypes are enough to build the synthetic dataset. They are not: `build-dictionary` reads the real files to compute histograms, category sets, missingness, value formats, sensitivity flags, temporal coverage and the join key, and `build-synthetic` draws from that dictionary. Headers plus dtypes alone give uniform fakes that break analysis code on real data.

What onboarding actually needs:

- Files the profiler can discover: `.csv` / `.tsv`, and since PR #9 `.parquet` / `.pq`.
- A recognizable subject-key column name (`time_traveler_id`, `subject_id`, `participant_id`, `public_client_id`, `user_id`, `record_id`, `id`). Profiling (`build-dictionary`) detects it by name only and has no override; `--join-keys` exists only on `build-synthetic`, where it changes which columns are remapped to the `SYNTH_` pool, not what was profiled.
- An authorized human operator to run profiling as `cs-exec`. No LLM reads raw data at any stage, including dictionary bootstrapping (auto memory [claude]).
- Optional: codebook files (`questions` / `response_options` under `raw/`) and `#` metadata lines in text files.

The dataset was parquet, so PR #9 (merge `6138798`; commits `9f665d0` initial, `83cf635` review fixes) added it. The first commit worked on the happy path; review then found four real gaps and one mostly-wrong claim. The lessons generalize to any new format.

## Guidance

### 1. One shared reader, then grep the whole repo for reader sites

Widen discovery (`discover_files(data_dir, exts=(".csv", ".tsv", ".parquet", ".pq"))`), then replace each `parse_file` + `pd.read_csv` pair with one `read_table()` that returns `(ParsedFile, DataFrame)`, so callers keep their shape:

```python
# src/gated_cs/profiler/parse.py
def is_parquet(path): return path.lower().endswith((".parquet", ".pq"))

def read_table(path: str):
    if is_parquet(path):
        nested = [f.name for f in pq.read_schema(path) if pa.types.is_nested(f.type)]
        if nested:
            raise ValueError(f"{path}: nested (list/struct/map) parquet columns are not "
                             f"supported, flatten them first: {', '.join(nested)}")
        df = pd.read_parquet(path)
        df.columns = [str(c) for c in df.columns]
        return ParsedFile(delimiter=None, header=list(df.columns)), df
    parsed = parse_file(path)
    header_line = max(parsed.data_start_line - 1, 0)
    df = pd.read_csv(path, sep=parsed.delimiter, skiprows=header_line,
                     header=0, low_memory=False)
    return parsed, df
```

The first commit moved `profile_file` and `_codebook_text` but missed `scripts/offline_reid_assess.py`, which had its own `load_df` copy and a bare `pd.read_csv(syn_path)`. That script is the pre-disclosure re-identification check, so the miss broke a safety check, not a feature. Audit with a repo-wide grep, not a package grep:

```bash
grep -rn "read_csv\|read_parquet\|parse_file" src scripts tests
```

Two hits are deliberately outside the profiler path: `gate/derive.py` `read_layer_frame` (derived layers, its own parquet reader) and `gate/run_analysis.py` (released outputs fed to `check_table`, CSV-only). Every other raw-data or synthetic reader should go through `read_table`.

### 2. Write synthetic data in the source format with profiled dtypes restored

The synthesizer emits Python floats, ints and strings. Code developed on synthetic data uses `.dt`, bool masks and categorical ops, so a parquet source needs a parquet sample with the real schema. The dictionary already records each column's dtype string; `_write_synthetic` casts back from it in both `build()` and `build_synthetic_from_dictionary()`:

```python
# src/gated_cs/profiler/build_dictionary.py (excerpt)
if dtype.startswith("datetime64"):
    out = pd.to_datetime(s, errors="coerce", utc=True, format="mixed")
    if "," not in dtype:
        return out.dt.tz_localize(None)
    return out.dt.tz_convert(dtype.split(",", 1)[1].rstrip("]").strip())  # read as UTC instant, shown in source zone
```

The snippet is an excerpt of `_restore_dtype`, whose body sits in `try: ... except (TypeError, ValueError): return s`: a column that won't cast stays as generated, since it is fabricated either way. Int columns with NaN become the matching nullable dtype (`int32` -> `Int32`, `uint8` -> `UInt8`); join keys still come from the shared `SYNTH_` pool, so a parquet sample joins to a CSV sample.

### 3. Fail closed on structure the profiler can't judge, detected from the schema

Nested parquet columns (list / struct / map) crashed profiling mid-build with `TypeError: unhashable type: 'numpy.ndarray'` in `nunique`. Detect them from `pq.read_schema` (free) instead of scanning values (expensive), and raise an error naming file and columns. Don't silently stringify or drop them: the sensitivity and SDC rules can't judge content they can't see, and the right flattening depends on meaning, so it belongs to the operator.

### 4. Leak tests must separate coincidence from leakage

Synthetic dates are drawn inside each column's coverage window, so a synthetic date matching a real one is expected. Assert the real guarantee instead: no real IDs anywhere, and no exact dates in the dictionary.

```python
for pid in REAL_IDS:
    assert pid not in dict_text and pid not in syn.astype(str).to_csv()
for day in real_days:
    assert day not in dict_text   # not the synthetic sample: window draws can coincide
```

This qualifies, and does not replace, the existing rule that birth dates never appear in any artifact (see Related).

### 5. Reproduce reviewer claims before acting on them

Greptile raised five findings (score 2/5). Each was reproduced first:

| Finding | Verdict |
|---|---|
| Re-id script reads parquet as CSV | Real, fixed |
| Nested columns crash profiling | Real, fail closed |
| tz-aware timestamps come back UTC | Real, fixed |
| API serves parquet as `text/csv` | Real, now `application/vnd.apache.parquet` by extension |
| "Boolean sample values are lost" | Mostly wrong |

Bool is a numeric dtype, so `profile_column` builds a histogram and the synthetic draws round-trip (reproduced 51/49 True/False). Only a constant bool column has no histogram and falls through to string generation. The narrow case was hardened (`"true"/"false"` label mapping) and the thread got the evidence; Greptile conceded. Rewriting the bool path would have been churn.

### 6. A new runtime dependency is not deployed until it's in the gate venv

`pyarrow>=14` is now a declared core dependency (`gate/derive.py` already read parquet, so it was needed implicitly before). Local tests passing in a fresh venv say nothing about existing ones; until a venv is re-synced (`pip install -e .`, or re-provision for `/opt/gated-cs` on the VMs) it can't read parquet. PR #12 moved the pyarrow import inside `read_table`'s parquet branch, so an un-synced host still profiles CSV/TSV; before that, a top-level import broke the whole profiler. Keep new format dependencies imported lazily at the format branch for the same reason. Same class as the earlier missing-scipy-on-the-gate incident (auto memory [claude]).

## Why This Matters

- A format added to the pipeline but not to the re-id check means parquet data either crashes or skips the pre-disclosure check. In a PHI TRE that is a governance failure.
- Synthetic samples exist so code written blind runs unchanged on real data. Wrong format or dtypes cost a gated round trip per mistake.
- A clear error naming file and columns beats both a crash inside `nunique` and silent coercion of data the profiler can't assess.
- Reviewers are right often enough to take seriously and wrong often enough to verify. Here 4 of 5 were real; in other repos Greptile has been right on every P1 (see Related). Verify in both directions.

## When to Apply

- Adding any new input format to the profiler or any TRE reader.
- Any refactor of raw-data I/O: rerun the repo-wide reader grep including `scripts/`.
- Changing the synthesizer or how the dictionary records dtypes.
- An endpoint starts serving a new file type.
- Adding a dependency the gate or the re-id check imports.
- Answering "what do you need from me to onboard a dataset?": use the list in Context.

## Examples

Re-id check reader, before (text-only):

```python
def load_df(path):
    parsed = parse_file(path)
    header_line = max(parsed.data_start_line - 1, 0)
    return pd.read_csv(path, sep=parsed.delimiter, skiprows=header_line, header=0, low_memory=False)
...
syn = pd.read_csv(syn_path)
```

After:

```python
def load_df(path):
    return read_table(path)[1]
...
syn = load_df(syn_path)
```

## Open items (as of 2026-10-26, after PR #12)

- ~~Leak-suite coverage gap~~ **Closed by PR #12:** all five mechanical non-disclosure tests are parametrized over csv and parquet sources (`fmt` fixture), and artifacts are decoded with `pd.read_parquet` instead of byte-scanned. Every parquet variant passed on first run, so no leak was hiding; the gap was coverage only.
- **Not deployed:** no VM gate venv has pyarrow yet, and the repo's own local `.venv` doesn't either. Since PR #12 that only blocks parquet; CSV profiling works regardless (`test_csv_profiling_works_without_pyarrow`).
- ~~Unknown timezone crashes the build~~ **Closed by PR #12:** `_restore_dtype` now also catches `KeyError` (`ZoneInfoNotFoundError` subclasses it), so an unrecognized zone such as a dateutil `tzfile(...)` repr leaves the fabricated column as generated. The zone is still recovered by string-splitting `str(dtype)`; recording `dtype.tz` as its own dictionary field would make it exact.
- **Round-trip limits:** date-only tz-aware columns shift by the zone offset (values are read as UTC instants); a parquet bool column with nulls loads as `object` and is not restored to bool.
- **Greptile never re-reviewed `83cf635`:** it does not auto re-review on push; PR #9 merged on fixes plus tests, not on a Greptile pass.
- **Newer pandas fails one existing test:** in a fresh venv (pandas 3.1), `test_profile_file_mixed_tz_timestamps_no_warning` fails on unmodified master because a `Pandas4Warning` (`Series.values` dropping tz info) trips its no-warning assertion. Unrelated to parquet; any newly built environment shows it.
- **Scope:** parquet is profiler input and synthetic output only. Gate-released outputs stay CSV-only; `check_table` still fails closed on non-CSV.

## Related

- `docs/solutions/best-practices/synthetic-data-sdc-mechanical-nondisclosure-gate-2026-07-22.md`: the leak-test rules this doc qualifies (birth dates never in any artifact still holds).
- `docs/solutions/security/host-boundary-scope.md`: gate release check is CSV-only, unchanged here.
- Vault `docs/solutions/best-practices/fail-closed-guards-must-not-no-op-on-absent-input-2026-07-13.md`: a guard wired on one input path but not another, and a case where Greptile's P1s were all real.
- PRs: https://github.com/trentleslie/gated-claude-code/pull/9 (feature), https://github.com/trentleslie/gated-claude-code/pull/12 (follow-ups)
