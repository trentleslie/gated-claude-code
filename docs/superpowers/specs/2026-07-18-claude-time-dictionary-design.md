# `claude-time` Dictionary Set for the TIME_SNAPSHOTS Wearable Cohort — Design Spec

> **For agentic workers:** implement via `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans`, task-by-task.

**Goal:** Produce a `claude-time` **dictionary set** — `dictionary.json` + `dictionary.md` +
`synthetic_samples/` — describing the TIME_SNAPSHOTS wearable + clinical cohort, by **generalizing the
existing `gated_cs.profiler` in place** so one hardened SDC codebase serves both the Arivale and TIME
studies. This dictionary is the first artifact of a future `claude-time` gated environment (the parallel
of claude-arivale); standing up that environment is out of scope here.

**Isolation invariant (unchanged from claude-arivale):** every byte of raw data is read only by scripts
running on the data box; only aggregate, k-anon-safe metadata (schema, missingness, cardinality,
suppressed-value flags, coarse coverage, synthetic rows) is ever surfaced off-box or into an assistant's
context. No raw row value is ever read into a human/assistant transcript.

**Tech stack:** Python (`gated_cs` package), pandas/numpy, stdlib `csv`. Runs in the gate venv on the
data box; developed and tested locally against synthetic fixtures.

## Source data (metadata-only recon, 2026-07-18)

- Location on box: `/procedure/data/local_data/TIME_SNAPSHOTS/`, foldered by device.
- 43 real CSVs (~956 MB) + 1 `.ipynb_checkpoints/` duplicate to exclude.

| Source folder | Files | Notes |
|---|---|---|
| `oura_ring` | 33 | Daily aggregates + high-frequency series; largest are `sleep_movement_30_sec` / `hypno30s_sleep_phase` (~210 MB each), `met` (153 MB), `temperature` (126 MB), `heartrate` (124 MB) |
| `smart_band` (Whoop) | 3 | `activities`, `daily_summaries`, `sleeps` |
| `stelo_cgm` | 1 | `processed/cgm_all_subjects` |
| `smart_scale` (Withings) | 1 | `all_metrics` |
| `redcap_demographics` | 1 | 14 KB — most re-identifying file |
| `redcap_questionnaires` | 4 | `raw/` = survey codebook (`questions`, `response_options`) + `responses_long`; `processed/` = joined Q&A |

Characteristics that diverge from Arivale's flat client-keyed CSVs: heterogeneous per-device schemas,
high-frequency longitudinal timestamps, wide "all_subjects" files, nested folders, and a mixed
wearable + clinical/survey payload.

## Global constraints

- The SDC core is **reused unchanged**; TIME support is added as generalizations around it, not as edits
  to the k-anon / suppression / histogram-edge logic.
- All profiling runs on the box against the real path; the repo change is developed/tested locally with
  synthetic fixtures only — no real TIME data is copied off-box or into the repo.
- Reproducibility per the experiment-hygiene SOP: the dictionary run records input file content-hashes,
  sizes, row counts, thresholds, and package versions; output is written to a timestamped on-box dir by
  default (not behind an opt-in flag).

## Decisions (locked during brainstorming, 2026-07-18)

- **Code strategy = generalize the shared profiler in place** (chosen over a standalone `claude-time`
  repo or a throwaway on-box script). One audited SDC path serves both studies; the only Arivale-specific
  thing today is a hardcoded join key, which becomes configurable.
- **Timestamps = coarse temporal coverage.** Exact per-row timestamps stay fully suppressed, but each
  datetime column emits non-identifying aggregate coverage: min/max **truncated to month**, and a
  sampling-cadence estimate (e.g. median inter-sample delta bucketed to a human label like "~1/5 min").
  This gives a Claude Science agent the study's temporal shape — the point of a longitudinal cohort —
  without exposing any real timestamp.
- **Codebook files surfaced as reference.** `redcap_questionnaires/raw/` `questions` and
  `response_options` are survey metadata (question text, allowed answers), not subject data; they are
  surfaced more fully so questionnaire columns are interpretable, rather than suppressed as if they were
  per-person rows. `responses_long` and `processed/` Q&A are profiled as normal subject data.

## 1. Recursive discovery & grouping

- Replace the flat `glob(data_dir/*.csv|*.tsv)` in `build_dictionary.build` with a **recursive walk**.
- Exclude any path containing `.ipynb_checkpoints/`.
- For each file, derive: `source` (top-level device folder, e.g. `oura_ring`), `stage` (`raw` |
  `processed` | `""`), and the relative path (dictionary key).
- The dictionary groups files by `source`; `dictionary.md` renders one section per device with its files
  nested under it. `synthetic_samples/` mirrors the relative folder structure.

## 2. Configurable & auto-detected subject key

- `build()` / `synthesize()` no longer default `join_keys=("public_client_id",)`. The join key becomes a
  config value with a **detection heuristic**: pick the column whose (case-insensitive) name matches a
  ranked list (`subject_id`, `participant_id`, `public_client_id`, `user_id`, `record_id`, `id`) and
  whose profile looks id-like. Detected key(s) recorded per file in the dictionary.
- Record **distinct-subject count (cohort N)** per file as aggregate metadata. A per-subject count is
  non-identifying and essential context (how many people, how complete each source is).
- Subject-id columns remain **value-suppressed** (existing `_id$`/`^id$` sensitivity rule); the id_pool
  substitution in synthetic samples uses the detected key name.

## 3. Large-file handling

- Add a size threshold (default 25 MB) above which `profile_file` reads the CSV in **chunks**
  (`pandas.read_csv(chunksize=...)`) and accumulates column statistics across chunks:
  running missing/non-null counts, a bounded value-set for cardinality/category counting (with a cap
  beyond which the column is treated as high-cardinality and suppressed), and streaming histogram counts
  against data-independent edges computed from a first cheap min/max pass (or a two-pass approach).
- k-anon guarantees are computed on **full** counts (chunk-accumulated), never on a sample, so no
  suppression threshold is weakened by chunking.
- Small files keep the existing single-`read_csv` path.

## 4. Coarse temporal coverage (new column facet)

- A datetime column is still flagged sensitive and its raw values suppressed. In addition, when a column
  is datetime-typed or name-matches the datetime pattern, emit a `temporal_coverage` block:
  `{ "min_month": "YYYY-MM", "max_month": "YYYY-MM", "cadence": "<human label>", "n_timestamps": <int> }`.
- `min_month`/`max_month` are computed on-box then truncated to month before emission (day-granular values
  never leave the box). `cadence` is the median inter-sample delta **per subject**, bucketed to a coarse
  human label (e.g. "~1/5 min", "~1/day"), so it reveals sampling design, not a person's schedule.
- No exact timestamp, and no per-subject timeline, is ever emitted.

## 5. Reference-codebook handling

- Files under `*/raw/` whose schema matches the REDCap codebook shape (a question-text column, a
  field/variable-name column, response-option enumerations) are tagged `role: codebook` and rendered in
  `dictionary.md` with their descriptive text surfaced (question labels, allowed answers) rather than
  value-suppressed. These files contain no per-person data.
- Detection is conservative: only `redcap_questionnaires/raw/questions*` and `response_options*` by name;
  anything ambiguous falls back to standard subject-data profiling.

## 6. Output & reproducibility

- `build()` writes to a **timestamped on-box output dir by default** (e.g.
  `~/claude-time-dictionary/<UTC-timestamp>/`), printing the path on completion; `--out` overrides.
- Output contains `dictionary.json`, `dictionary.md`, `synthetic_samples/<mirrored tree>`, and a
  `run_manifest.json` pinning per-file content-hash + size + row_count, thresholds, detected join keys,
  and `pip freeze` of the gate venv.

## 7. Testing (TDD, synthetic fixtures only)

- Fixtures under `tests/fixtures/` mimicking the TIME shape: nested device folders, a `.ipynb_checkpoints`
  dir that must be skipped, a wide high-frequency file (subject_id + timestamp + numeric series), a
  demographics-like file, and a REDCap-style `raw/` codebook pair.
- Assertions:
  - recursive walk finds exactly the real CSVs and **excludes** checkpoint dupes.
  - no raw cell value from any fixture appears in `dictionary.json` or a synthetic sample (leak test).
  - k-anon holds after chunked profiling: a value occurring `< k` times never appears as a category;
    chunked and single-read profiling of the same fixture agree.
  - datetime columns emit only month-granular coverage + a cadence label; no day/second value leaks.
  - detected join key and cohort-N are correct; id columns are suppressed.
  - codebook files surface question/answer text; non-codebook files do not.

## Non-goals / YAGNI (v1)

- Provisioning the `claude-time` gated **environment** (users, sandbox, gate verbs) — downstream, separate
  spec.
- The derived-data layer (that is the 2026-07-17 spec's concern).
- Realistic temporal synthesis — synthetic samples stay per-column-independent (privacy-preferred);
  they demonstrate schema/units, not real dynamics.
- Cross-file / cross-device join modeling in synthetic samples.

## Dependencies / context this fits

- Extends `src/gated_cs/profiler/` (`build_dictionary.py`, `profile.py`, `parse.py`, `synthesize.py`,
  `sensitivity.py`) — the same module claude-arivale's dictionary is built from.
- Sibling to the 2026-07-17 derived-data-layer spec; both share the SDC core and dictionary surface.
- Run target: `/procedure/data/local_data/TIME_SNAPSHOTS/` on the current Claude Science box (IP is
  ephemeral; reach it via the `claude-science-vm` SSH alias, re-pointed per session).
