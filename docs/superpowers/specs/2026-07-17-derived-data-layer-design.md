# Derived-Data Layer for the Gated Arivale TRE — Design Spec

> **For agentic workers:** implement via `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans`, task-by-task.

**Goal:** Extend the gated code-to-data TRE so a job can compute *per-person derived features*
(imputation, biological-age clocks, uniqueness scores, ratios, …) and persist them **inside the PHI
boundary** for reuse by future gated analyses — while only aggregates ever leave. v1 ships the general
framework plus **one exemplar layer: metabolomics imputation**.

**Architecture:** A `cs-exec`-owned derived store (`/var/gate/derived/`, mode `0700`) parallel to the raw
data, mounted **read-only** into every sandbox so any analysis can reuse existing layers. A new
`submit-derivation` verb (shared executor, "derivation mode") adds one writable `LAYER_DIR` bind whose
contents persist to the store **un-gate-checked and are never delivered to `cs-gated`**, while
`OUTPUT_DIR` continues to release only gate-checked fit-quality aggregates. Each layer carries an
executor-written provenance manifest and is auto-profiled into the dictionary + synthetic surface so the
model can develop against it without seeing real derived values.

**Tech stack:** Python (`gated_cs` package), bubblewrap sandbox, pandas/numpy/scikit-learn/scipy/
statsmodels (gate venv `/opt/gated-cs`), parquet (pyarrow) or gzip-TSV.

## Global constraints

- The isolation invariant is unchanged: **exactly one identity (`cs-exec`) reads real per-person data —
  raw OR derived — and every path out passes through the gate's SDC.**
- `submit-analysis` behavior is unchanged except it gains a **read-only** mount of the derived store; it
  can never persist a layer.
- Only `submit-derivation` can create a layer; it is a distinct, separately-audited verb.
- Derived per-person values are PHI: never released as rows; aggregates go through the existing SDC
  (k=5 min cell, row cap, identifier/date suppression, error scrubbing).
- Provenance is written by `cs-exec` (the executor), never by the untrusted child.
- Reproducibility per the experiment-hygiene SOP: pin input content-hashes, params, seed, and gate-venv
  package versions for every layer.

## Decisions (locked during brainstorming)

- **Write path = Approach A** — a distinct `submit-derivation` verb over a *shared* executor (chosen over
  a flag on `submit-analysis` or an implicit output-subdir convention). Creating a persistent per-person
  layer is a higher-consequence action than releasing an aggregate, so it gets its own verb, audit
  verdict, and provenance step; `submit-analysis` stays trivially safe (never persists).
- **Trust model = Hybrid** — a successful derivation **auto-persists and auto-profiles** (so the
  autonomous pipeline self-extends the substrate), but every layer MUST carry released fit-quality
  aggregates + a provenance manifest, and any wiki finding surfaces which derived layers it depends on
  and their quality. Bad layers are caught at the (private-wiki) review stage, not blocked at creation.
- **v1 exemplar = metabolomics imputation** — it exercises every hard path (fit-on-real-data-in-sandbox,
  persist-per-person, release-quality-only) and yields a denser matrix that improves downstream analyses.

---

## 1. Derived store & ownership

- **`/var/gate/derived/`**, owned `cs-exec:cs-exec`, mode **`0700`** — deliberately *not* the `csbridge`
  group used by the rest of `/var/gate`. This is the whole safety basis: `cs-gated` cannot even traverse
  it, so per-person derived values are never directly readable and can leave only as gate-checked
  aggregates, exactly like raw data.
- **One subdir per layer**, global and shared (reusable across all analyses, not per-analysis):
  ```
  /var/gate/derived/<layer>/
    data.parquet        # per-person derived matrix, keyed by public_client_id
    MANIFEST.json       # authoritative provenance (Section 3)
    PROVENANCE.jsonl    # append-only (re)derivation history (Section 3)
    model.pkl           # optional fitted model, for reproducibility / re-application
  ```
  Parquet if `pyarrow` is present in the gate venv; otherwise gzip-TSV (implementation detail).
- **Symmetry with raw:** raw data and the derived store are both `cs-exec`-owned and both mounted
  read-only into every sandbox for reading. The derived store is simply a second read source; the model
  develops against its *synthetic shadow* (Section 4), never the real values.

## 2. Two verbs, one shared executor

The current executor (`src/gated_cs/gate/run_analysis.py`) is refactored to take optional binds + a mode;
both verbs run through it.

**`submit-analysis <script>` — unchanged behavior, one addition.** Sandbox mounts: raw data **RO**, the
derived store **RO** (new — analyses can now reuse existing layers, exposed as `DERIVED_DIR`), and
`OUTPUT_DIR` writable. Everything in `OUTPUT_DIR` is gate-checked → released aggregates. It never persists.

**`submit-derivation <script> --layer <name>` — the new verb** → `sudo -u cs-exec /opt/gate/run-derivation`
(a thin wrapper like `run-analysis`; a **second NOPASSWD sudoers rule** for `cs-gated`). Same sandbox
**plus one writable bind**, a staging dir for the new layer, exposed as `LAYER_DIR`:

```
derivation sandbox binds:
  DATA_DIR    (raw)                  → read-only
  DERIVED_DIR (/var/gate/derived)    → read-only    (fit on raw + existing layers)
  LAYER_DIR   (staging/<name>)       → WRITABLE      → persisted to store; NEVER gate-checked; NEVER delivered
  OUTPUT_DIR  (out_dir)              → WRITABLE      → gate-checked → releases fit-quality aggregates only
```

The two writable targets have different fates: `OUTPUT_DIR` → gate → possibly `cs-gated`;
`LAYER_DIR` → store → never `cs-gated`. On a clean child exit, the executor: (a) validates the layer
output (readable, keyed by `public_client_id`, expected shape); (b) moves it from staging to
`/var/gate/derived/<name>/`; (c) writes MANIFEST + appends PROVENANCE (Section 3); (d) profiles the layer
into the dictionary + synthetic surface (Section 4); (e) gate-checks and delivers the `OUTPUT_DIR`
fit-quality aggregates as normal. It records a distinct **`derivation`** audit verdict.

## 3. Provenance & versioning

Every layer is reproducible by construction, and provenance is written by **`cs-exec`, not the child**.

- **`MANIFEST.json`** (authoritative): layer name; the derivation script's `sha256` content hash (the same
  hashing the audit uses); **input provenance** — which raw tables and existing derived layers were read,
  each with a content hash (+ dictionary version / raw-snapshot hash); **params + seed**; **gate-venv
  package versions**; the derived-matrix **schema** (columns, dtypes, n persons, missingness); a
  **content hash of `data.parquet`**; and a copy of the **fit-quality summary** (e.g., CV R²).
- **`PROVENANCE.jsonl`** (append-only, like the audit log): one line per (re)derivation, never
  overwritten — the layer's full history survives regeneration of `data.parquet`.
- The child may drop a `_params.json` in `LAYER_DIR` declaring intent/params, but the executor computes
  the load-bearing hashes/versions itself, so provenance cannot be forged by the model's code.

**Versioning (deliberately simple for v1):** `data.parquet` is "latest"; re-deriving overwrites it but
appends a new `PROVENANCE.jsonl` line, so history is never lost. Downstream analyses reference a layer by
name; the content hash in each provenance line is the pin if hard version addressing (`<name>@<hash>`) is
needed later (YAGNI — not built in v1).

## 4. Dictionary & synthetic extension

On a successful `submit-derivation`, immediately after the layer is persisted, the executor (`cs-exec`)
runs the **same deterministic profiler** (`profile` / `sensitivity` / `synthesize`) on the derived matrix,
treating it as just another table:

- **Dictionary:** appends the layer's entry to `/var/gate/dict/dictionary.{json,md}` under the same
  disclosure rules (no raw min/max, k-anon, identifier/date suppression). The entry is tagged **`derived`**
  with a pointer to its manifest, so the model knows it is derived and can see its fit-quality, and so the
  wiki review can surface which derived layers a finding depends on (the transparency half of the hybrid
  model).
- **Synthetic surface:** generates a synthetic shadow keyed on the **same shared `SYNTH_` id pool** as the
  other synthetic tables, so a script can join synthetic derived ⋈ synthetic raw on `public_client_id`,
  develop + self-test, then submit to run on real data. Reuses the existing relational synthesizer.
- The update is **incremental** — profile only the new layer and merge it into the existing dictionary +
  add one synthetic file; not a full rebuild.

Net effect: derived layers become first-class citizens of the dictionary/synthetic, indistinguishable
from raw tables to the model. The "model never sees a real value" invariant holds identically for derived
and raw.

## 5. Disclosure rules & limitations

Governing principle: a derived per-person value is still PHI, so **nothing changes about how data leaves.**
There is exactly one release path — the existing gate on `OUTPUT_DIR` — and it applies to derived
features identically:

- **No per-person derived rows out.** The derived matrix lives only in the store; any attempt to release
  it as rows via `OUTPUT_DIR` hits the same `check_table` SDC and is quarantined.
- **Aggregates of derived features go through the same gate** (k=5, row cap, suppression). No new release
  surface.

Two derived-specific limitations, on the record with their backstops:

1. **Re-encoding suppressed information.** A derivation could compute a feature that is a deterministic
   function of a field the dictionary suppressed (a date, a near-identifier); releasing aggregates of that
   feature could leak what suppression was meant to hide. **Mitigation:** the derived layer is run through
   the *same* profiler sensitivity screening (identifier/date detection) → a derived column that looks
   identifier- or date-like is flagged sensitive and suppressed like any raw one. This catches obvious
   cases; a deliberately obfuscated re-encoding could evade the heuristic, so the backstops are the
   append-only audit (every derivation logged by script hash) and human review at the wiki.
2. **Differencing surface grows with feature count.** Derived features do not create a new *class* of
   leak — SDC already cannot fully defeat cross-query differencing — but more features and an *autonomous*
   query loop multiply the overlapping-aggregate surface. **Mitigation:** the audit log is ground truth;
   a periodic differencing review (and optionally a query-volume signal) is the backstop, flagged for
   governance, not a v1 blocker.

## 6. Exemplar: metabolomics imputation

The v1 layer that proves the framework — `metabolomics_imputed`:

- **Derivation script** (`analyses/NN-impute-metabolomics/impute.py`, run via
  `submit-derivation --layer metabolomics_imputed`): reads `metabolomics_corrected` (real, RO); **fits an
  imputer inside the sandbox** (e.g. sklearn `IterativeImputer`/`KNNImputer`) — the model runs as
  `cs-exec`, sandboxed, so `cs-gated` never sees rows or the fitted model; writes the **imputed per-person
  matrix → `LAYER_DIR`** (persisted, never released); writes **fit-quality → `OUTPUT_DIR`** —
  mask-and-predict cross-validated R²/RMSE per metabolite, overall CV R², %-missing before/after, n
  (gate-checked, released so the layer's quality is visible); optionally `model.pkl → LAYER_DIR`.
- **On success:** executor validates shape/key, moves to `/var/gate/derived/metabolomics_imputed/`,
  writes MANIFEST (`metabolomics_corrected` hash, params, sklearn version, seed, schema, CV-R²) +
  `PROVENANCE.jsonl`, and profiles the layer into dictionary + synthetic.
- **Reuse:** a later `submit-analysis` reads `DERIVED_DIR/metabolomics_imputed` (RO) — e.g. re-runs the
  metabolome→genus discovery on the denser matrix — releasing aggregates as usual, developed against the
  synthetic imputed layer.

## 7. Testing

Test-first, mirroring the existing red-team suite:

- **Executor unit:** `LAYER_DIR` writable → store (not gate-checked); `OUTPUT_DIR` still gate-checked;
  `DERIVED_DIR` RO mount present in both verbs.
- **Adversarial isolation (load-bearing):** `cs-gated` gets permission-denied on `/var/gate/derived`; a
  derivation writing raw rows to `OUTPUT_DIR` is still quarantined; raw rows written to `LAYER_DIR`
  persist but are **unreadable by `cs-gated`** (proving the store is not an exfil channel); a child
  cannot forge `MANIFEST.json` (the executor's authoritative copy wins).
- **Sensitivity screening:** a derived column re-encoding a date/identifier is flagged + suppressed.
- **Synthetic development:** the derived layer profiles into dictionary + synthetic; synthetic derived ⋈
  synthetic raw on the `SYNTH_` pool returns non-empty.
- **End-to-end on fixtures:** `submit-derivation` → layer persisted + profiled + quality released; then
  `submit-analysis` reading the derived layer → aggregate released.

## Non-goals / YAGNI (v1)

- Versioned `<name>@<hash>` addressing (the provenance content hash is the pin if needed later).
- Derived layers beyond imputation (biological-age clocks, gut uniqueness, mNODE/MelonnPan predicted
  metabolites, metabolite ratios, PRS residuals) — follow-ons once the framework works.
- Query-volume governance / an automated differencing monitor — a governance backstop, not built in v1.
- Unrelated cleanup (e.g. the dangling `clerk-*` skill symlinks on the analyst box).

## Dependencies / context this fits

Highest-leverage piece of the planned autonomous discovery pipeline (`claude -p` as `cs-gated` in cron;
literature radar via WebSearch/eutils; the `/replicate` + `/validate` skills; open validation cohorts
under `~/analysis/validation/`). Reports auto-publish to the **private** Outline wiki, which is the human
review stage. Goal: PHI-safe, validation-first discovery of high-impact T2D / Alzheimer's insights.
