# claude-time Dictionary Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the shared `gated_cs.profiler` in place so it can build a `claude-time` dictionary set (`dictionary.json` + `dictionary.md` + `synthetic_samples/`) from the nested, heterogeneous, longitudinal TIME_SNAPSHOTS wearable + clinical cohort — without ever reading a raw row value off-box.

**Architecture:** Add four focused capabilities *around* the untouched SDC core: (1) recursive device-foldered discovery, (2) subject-key auto-detection + cohort-N, (3) coarse month-granular temporal coverage for datetime columns, (4) chunked profiling for large files. Then wire them into `profile_file` and `build`, add a timestamped default output dir + run manifest, and render codebook files as reference. All new logic is developed and tested locally against synthetic fixtures; the real run happens on the data box.

**Tech Stack:** Python 3.12/3.13, pandas, numpy, stdlib `csv`/`os`, pytest.

## Global Constraints

- **Isolation invariant:** every byte of raw data is read only by scripts on the data box; only aggregate, k-anon-safe metadata ever surfaces off-box or into an assistant's context. No raw row value is ever read into a transcript. (Enforced by tests, not trust.)
- **SDC core reused unchanged:** k-anonymity `k=5`, rare-category suppression, high-cardinality suppression, data-independent "nice" histogram edges, full value suppression for sensitive/near-unique/identifier/datetime columns, per-column-independent synthetic samples. New code wraps this logic; it does not edit it.
- **k-anon computed on full counts, never a sample** — every file is read whole and profiled per-column.
- **Timestamps:** exact per-row timestamps stay suppressed; datetime columns emit only month-granular min/max + a bucketed cadence estimate.
- **Reproducibility (experiment-hygiene SOP):** `build()` writes to a timestamped output dir *by default* (not behind a flag), prints the path on completion, and writes a `run_manifest.json` pinning per-file content-hash + size + row_count, thresholds, detected join keys, and gate-venv package versions. `--out` is an override.
- **No new third-party deps** beyond pandas/numpy already in the gate venv.

> **Plan amendment (2026-07-18, during execution):** Task 4's chunked large-file path was dropped by decision. The `list(reader)` implementation did not actually bound memory and risked per-chunk dtype divergence, so `profile_file_chunked` / `_finalize_numeric` / the `large_file_bytes` + `chunk_rows` thresholds are removed. The behaviour-preserving `_nice_edges` refactor stays. All files are profiled with a single whole-file read (`build()` already processes one file at a time, so peak memory ≈ one file); Task 8's on-box run verifies this holds for the ~210 MB Oura files. `Thresholds` instead carries `cadence_sample_rows: int = 200_000` for Task 5's cadence sampling. Tasks 5 & 6 below are updated accordingly.

---

### Task 1: Recursive device-foldered discovery

**Files:**
- Create: `src/gated_cs/profiler/discover.py`
- Test: `tests/profiler/test_discover.py`

**Interfaces:**
- Produces: `DiscoveredFile(path: str, relpath: str, source: str, stage: str, role: str)` dataclass and `discover_files(data_dir: str, exts=(".csv", ".tsv")) -> list[DiscoveredFile]`. `source` = top-level folder under `data_dir` (`""` if file is at root); `stage` ∈ {`"raw"`, `"processed"`, `""`}; `role` ∈ {`"data"`, `"codebook"`}. Excludes any path under `.ipynb_checkpoints/`. Returns list sorted by `relpath`.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiler/test_discover.py
import os
from gated_cs.profiler.discover import discover_files, DiscoveredFile

def _touch(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("x")

def test_discover_walks_devices_excludes_checkpoints_and_tags(tmp_path):
    base = str(tmp_path)
    _touch(os.path.join(base, "oura_ring", "TIME_oura_daily_sleep_20260610.csv"))
    _touch(os.path.join(base, "stelo_cgm", "processed", "TIME_cgm_all_subjects.csv"))
    _touch(os.path.join(base, "redcap_questionnaires", "raw", "TIME_redcap_questions.csv"))
    _touch(os.path.join(base, "redcap_questionnaires", "raw", "TIME_redcap_response_options.csv"))
    _touch(os.path.join(base, "redcap_questionnaires", "raw", "TIME_redcap_responses_long.csv"))
    _touch(os.path.join(base, "stelo_cgm", "processed", ".ipynb_checkpoints",
                        "TIME_cgm_all_subjects-checkpoint.csv"))
    _touch(os.path.join(base, "oura_ring", "notes.txt"))  # non-csv ignored

    found = discover_files(base)
    rels = [f.relpath for f in found]

    assert not any(".ipynb_checkpoints" in r for r in rels)
    assert not any(r.endswith("notes.txt") for r in rels)
    assert len(found) == 5
    by_rel = {f.relpath: f for f in found}
    sleep = by_rel[os.path.join("oura_ring", "TIME_oura_daily_sleep_20260610.csv")]
    assert sleep.source == "oura_ring" and sleep.stage == "" and sleep.role == "data"
    cgm = by_rel[os.path.join("stelo_cgm", "processed", "TIME_cgm_all_subjects.csv")]
    assert cgm.source == "stelo_cgm" and cgm.stage == "processed" and cgm.role == "data"
    q = by_rel[os.path.join("redcap_questionnaires", "raw", "TIME_redcap_questions.csv")]
    assert q.stage == "raw" and q.role == "codebook"
    opts = by_rel[os.path.join("redcap_questionnaires", "raw", "TIME_redcap_response_options.csv")]
    assert opts.role == "codebook"
    long = by_rel[os.path.join("redcap_questionnaires", "raw", "TIME_redcap_responses_long.csv")]
    assert long.role == "data"  # raw but not a codebook stem
    assert rels == sorted(rels)  # sorted output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_discover.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gated_cs.profiler.discover'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gated_cs/profiler/discover.py
import os
from dataclasses import dataclass

CHECKPOINT_DIR = ".ipynb_checkpoints"
_STAGES = ("raw", "processed")
_CODEBOOK_STEMS = ("questions", "response_options")

@dataclass
class DiscoveredFile:
    path: str
    relpath: str
    source: str
    stage: str
    role: str

def _classify_role(stage: str, filename: str) -> str:
    if stage == "raw":
        low = filename.lower()
        for stem in _CODEBOOK_STEMS:
            if stem in low:
                return "codebook"
    return "data"

def discover_files(data_dir: str, exts=(".csv", ".tsv")) -> list:
    out = []
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = [d for d in dirs if d != CHECKPOINT_DIR]  # prune, don't descend
        for fn in sorted(files):
            if not fn.lower().endswith(tuple(exts)):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, data_dir)
            parts = rel.split(os.sep)
            source = parts[0] if len(parts) > 1 else ""
            stage = next((p for p in parts if p in _STAGES), "")
            out.append(DiscoveredFile(full, rel, source, stage, _classify_role(stage, fn)))
    return sorted(out, key=lambda f: f.relpath)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_discover.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gated_cs/profiler/discover.py tests/profiler/test_discover.py
git commit -m "feat(profiler): recursive device-foldered discovery with checkpoint exclusion + codebook tagging"
```

---

### Task 2: Subject-key auto-detection + cohort-N

**Files:**
- Create: `src/gated_cs/profiler/subject_key.py`
- Test: `tests/profiler/test_subject_key.py`

**Interfaces:**
- Produces: `SUBJECT_KEY_CANDIDATES: tuple[str, ...]`, `detect_subject_key(columns: list[str]) -> str | None` (case-insensitive, returns the *actual* column name), and `cohort_n(series) -> int` (distinct non-null count).

- [ ] **Step 1: Write the failing test**

```python
# tests/profiler/test_subject_key.py
import pandas as pd
from gated_cs.profiler.subject_key import detect_subject_key, cohort_n

def test_detect_prefers_specific_then_falls_back():
    assert detect_subject_key(["Subject_ID", "ts", "hr"]) == "Subject_ID"
    assert detect_subject_key(["ts", "user_id", "steps"]) == "user_id"
    assert detect_subject_key(["record_id", "public_client_id"]) == "public_client_id"
    assert detect_subject_key(["ts", "value"]) is None

def test_cohort_n_counts_distinct_nonnull():
    s = pd.Series(["a", "a", "b", None, "c", "c"])
    assert cohort_n(s) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_subject_key.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gated_cs.profiler.subject_key'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gated_cs/profiler/subject_key.py
# Ranked most-specific first; detection returns the first candidate present.
SUBJECT_KEY_CANDIDATES = (
    "subject_id", "participant_id", "public_client_id",
    "user_id", "record_id", "id",
)

def detect_subject_key(columns):
    lower = {c.lower(): c for c in columns}
    for cand in SUBJECT_KEY_CANDIDATES:
        if cand in lower:
            return lower[cand]
    return None

def cohort_n(series):
    return int(series.nunique(dropna=True))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_subject_key.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gated_cs/profiler/subject_key.py tests/profiler/test_subject_key.py
git commit -m "feat(profiler): subject-key auto-detection + cohort-N"
```

---

### Task 3: Coarse temporal coverage

**Files:**
- Create: `src/gated_cs/profiler/temporal.py`
- Test: `tests/profiler/test_temporal.py`

**Interfaces:**
- Produces:
  - `month_bounds(min_ts, max_ts) -> dict` → `{"min_month": "YYYY-MM", "max_month": "YYYY-MM"}` from two `pandas.Timestamp`s.
  - `bucket_cadence(median_seconds: float | None) -> str` → human label.
  - `cadence_label(ts_sample, sid_sample=None) -> str` → per-subject median inter-sample delta (falls back to global if no subject ids), bucketed. Computed on a **sample** (caller caps rows) — it describes sampling design, not any person's schedule.
  - `is_datetime_name(name: str) -> bool` → matches `date|time|timestamp|_at$`.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiler/test_temporal.py
import numpy as np
import pandas as pd
from gated_cs.profiler.temporal import (
    month_bounds, bucket_cadence, cadence_label, is_datetime_name,
)

def test_month_bounds_truncates_to_month():
    b = month_bounds(pd.Timestamp("2024-01-15 03:22:00"), pd.Timestamp("2026-06-30 23:59:00"))
    assert b == {"min_month": "2024-01", "max_month": "2026-06"}

def test_bucket_cadence_labels():
    assert bucket_cadence(30) == "~1/min or finer"
    assert bucket_cadence(300) == "~1/5 min"
    assert bucket_cadence(86400) == "~1/day"
    assert bucket_cadence(None) == "unknown"

def test_cadence_label_is_per_subject():
    # subject A every 5 min, subject B every 5 min, interleaved -> ~1/5 min
    base = pd.Timestamp("2025-01-01")
    tsA = [base + pd.Timedelta(minutes=5 * i) for i in range(10)]
    tsB = [base + pd.Timedelta(minutes=5 * i) for i in range(10)]
    ts = pd.Series(tsA + tsB)
    sid = pd.Series(["A"] * 10 + ["B"] * 10)
    assert cadence_label(ts, sid) == "~1/5 min"

def test_is_datetime_name():
    assert is_datetime_name("timestamp") and is_datetime_name("created_at")
    assert is_datetime_name("bedtime_start") and not is_datetime_name("heart_rate")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_temporal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gated_cs.profiler.temporal'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/gated_cs/profiler/temporal.py
import re
import numpy as np
import pandas as pd

_DATETIME_NAME = re.compile(r"date|time|timestamp|_at$", re.I)

# (upper-bound seconds, label); first bucket whose bound >= median wins
_CADENCE_BUCKETS = (
    (60, "~1/min or finer"),
    (300, "~1/5 min"),
    (900, "~1/15 min"),
    (3600, "~1/hour"),
    (21600, "~1/6 hours"),
    (86400, "~1/day"),
    (604800, "~1/week"),
)

def is_datetime_name(name: str) -> bool:
    return bool(_DATETIME_NAME.search(name or ""))

def month_bounds(min_ts, max_ts) -> dict:
    return {"min_month": pd.Timestamp(min_ts).strftime("%Y-%m"),
            "max_month": pd.Timestamp(max_ts).strftime("%Y-%m")}

def bucket_cadence(median_seconds) -> str:
    if median_seconds is None or not np.isfinite(median_seconds) or median_seconds <= 0:
        return "unknown"
    for bound, label in _CADENCE_BUCKETS:
        if median_seconds <= bound:
            return label
    return "~coarser than weekly"

def _median_delta_seconds(ts_sample, sid_sample) -> float | None:
    ts = pd.to_datetime(ts_sample, errors="coerce")
    frame = pd.DataFrame({"ts": ts.values})
    if sid_sample is not None:
        frame["sid"] = pd.Series(list(sid_sample)[: len(frame)]).values
    frame = frame.dropna(subset=["ts"])
    if frame.shape[0] < 2:
        return None
    if "sid" in frame:
        per = []
        for _, g in frame.groupby("sid"):
            s = g["ts"].sort_values()
            if s.shape[0] >= 2:
                per.append(s.diff().dropna().dt.total_seconds().median())
        vals = [v for v in per if v is not None and np.isfinite(v)]
        return float(np.median(vals)) if vals else None
    s = frame["ts"].sort_values()
    return float(s.diff().dropna().dt.total_seconds().median())

def cadence_label(ts_sample, sid_sample=None) -> str:
    return bucket_cadence(_median_delta_seconds(ts_sample, sid_sample))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_temporal.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gated_cs/profiler/temporal.py tests/profiler/test_temporal.py
git commit -m "feat(profiler): coarse month-granular temporal coverage + per-subject cadence buckets"
```

---

### Task 4: Chunked profiling for large files (histogram-edge refactor + equivalence)

**Files:**
- Modify: `src/gated_cs/config.py` (add size/chunk thresholds)
- Modify: `src/gated_cs/profiler/profile.py` (extract `_nice_edges`; add `profile_file_chunked`)
- Test: `tests/profiler/test_chunked.py`

**Interfaces:**
- Consumes: `Thresholds` from Task's config change; existing `profile_column`, `_histogram` in `profile.py`.
- Produces: `profile_file_chunked(path, thresholds=DEFAULTS, chunk_rows=None) -> dict` with the **same column-dict shape** as `profile_file`. Exact-equivalence guaranteed by reusing identical bin edges and `pd.cut` semantics, accumulating counts across chunks.
- Config gains `Thresholds.large_file_bytes: int = 25_000_000` and `Thresholds.chunk_rows: int = 200_000`.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiler/test_chunked.py
import numpy as np
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.profile import profile_file, profile_file_chunked

def _write(tmp_path):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "subject_id": rng.integers(0, 30, size=5000).astype(str),
        "hr": rng.integers(40, 180, size=5000),
        "quality": rng.choice(["good", "fair", "poor"], size=5000),
    })
    p = tmp_path / "big.csv"
    df.to_csv(p, index=False)
    return str(p)

def test_chunked_matches_single_read(tmp_path):
    path = _write(tmp_path)
    single = profile_file(path, DEFAULTS)
    chunked = profile_file_chunked(path, DEFAULTS, chunk_rows=337)  # deliberately ragged
    assert single["row_count"] == chunked["row_count"] == 5000
    for col in ("hr", "quality"):
        assert chunked["columns"][col] == single["columns"][col], col
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_chunked.py -v`
Expected: FAIL with `ImportError: cannot import name 'profile_file_chunked'`

- [ ] **Step 3a: Add config thresholds**

```python
# src/gated_cs/config.py
from dataclasses import dataclass
@dataclass(frozen=True)
class Thresholds:
    k: int = 5
    row_cap: int = 20
    cardinality_cap: int = 50
    bin_min_count: int = 5
    large_file_bytes: int = 25_000_000
    chunk_rows: int = 200_000
DEFAULTS = Thresholds()
```

- [ ] **Step 3b: Refactor `_histogram` to share `_nice_edges`, then add chunked profiler**

In `src/gated_cs/profiler/profile.py`, replace the body of `_histogram` that computes edges with a call to a new `_nice_edges`, and add `_accumulate_column` + `profile_file_chunked`. `_nice_edges` is the exact edge math already in `_histogram`:

```python
# src/gated_cs/profiler/profile.py  (additions / refactor)
import pandas as pd
import numpy as np
from .parse import parse_file

def _nice_edges(lo_v, hi_v, thresholds):
    step = _nice_step(hi_v - lo_v)
    start = math.floor(lo_v / step) * step
    end = (math.floor(hi_v / step) + 1) * step
    edges, e = [], start
    while e <= end + step / 2:
        edges.append(round(e, 10))
        e += step
    return edges

# _histogram now uses _nice_edges (replace the inline edge loop with):
#     edges = _nice_edges(lo_v, hi_v, thresholds)
# and keep the existing pd.cut / bin_min_count filtering below it.

def _finalize_numeric(counts_by_interval, thresholds):
    out = []
    for interval, count in counts_by_interval.sort_index().items():
        if int(count) >= thresholds.bin_min_count:
            out.append({"lo": float(interval.left), "hi": float(interval.right), "count": int(count)})
    return out

def profile_file_chunked(path, thresholds=DEFAULTS, chunk_rows=None):
    parsed = parse_file(path)
    header_line = max(parsed.data_start_line - 1, 0)
    chunk_rows = chunk_rows or thresholds.chunk_rows
    reader = pd.read_csv(path, sep=parsed.delimiter, skiprows=header_line, header=0,
                         low_memory=False, chunksize=chunk_rows)
    chunks = list(reader)  # skinny iteration; released after pass below
    row_count = int(sum(c.shape[0] for c in chunks))
    cols = {}
    for name in parsed.header:
        series_all = pd.concat([c[name] for c in chunks], ignore_index=True)
        col = profile_column(series_all, name=name, thresholds=thresholds)
        if name in parsed.column_descriptions:
            col["description"] = parsed.column_descriptions[name]
        cols[name] = col
    return {"path": path, "delimiter": parsed.delimiter, "row_count": row_count,
            "file_metadata": parsed.file_metadata, "columns": cols}
```

> **Note for the implementer:** this v1 chunked path concatenates one column at a time (never the whole frame), which bounds peak memory to the largest single column and is sufficient for the 210 MB TIME files (their widest column fits in memory comfortably). The `chunk_rows` seam and per-column accumulation are in place so a future pass can switch to true streaming `pd.cut` accumulation via `_nice_edges` + `_finalize_numeric` without changing the interface. Reusing `profile_column` guarantees exact equivalence with the single-read path — which is what the test asserts.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_chunked.py tests/profiler/test_profile.py -v`
Expected: PASS (equivalence holds; existing profile tests still green after the `_nice_edges` refactor)

- [ ] **Step 5: Commit**

```bash
git add src/gated_cs/config.py src/gated_cs/profiler/profile.py tests/profiler/test_chunked.py
git commit -m "feat(profiler): chunked large-file profiling + shared _nice_edges refactor (single-read equivalent)"
```

---

### Task 5: Wire temporal coverage + cohort-N + join-key into `profile_file`

**Files:**
- Modify: `src/gated_cs/profiler/profile.py` (`profile_file` and `profile_file_chunked` gain temporal + subject-key facets)
- Test: `tests/profiler/test_profile_facets.py`

**Interfaces:**
- Consumes: `temporal.is_datetime_name/month_bounds/cadence_label`, `subject_key.detect_subject_key/cohort_n`.
- Produces: `profile_file(...)` result dict gains top-level `"subject_key": str | None` and `"cohort_n": int | None`; each datetime column dict gains `"temporal_coverage": {min_month, max_month, n_timestamps, cadence}` (in addition to staying `sensitive`/suppressed). Signature adds keyword `sample_rows: int | None = None` (defaults to `thresholds.cadence_sample_rows`) bounding the cadence sample.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiler/test_profile_facets.py
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.profile import profile_file

def _write(tmp_path):
    rows = []
    for sid in range(20):
        for i in range(48):  # every 30 min across ~1 day
            rows.append({"subject_id": f"S{sid:03d}",
                         "timestamp": pd.Timestamp("2025-03-01") + pd.Timedelta(minutes=30 * i),
                         "hr": 50 + (i % 40)})
    p = tmp_path / "hr.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)

def test_profile_file_emits_subject_key_cohort_and_temporal(tmp_path):
    prof = profile_file(_write(tmp_path), DEFAULTS)
    assert prof["subject_key"] == "subject_id"
    assert prof["cohort_n"] == 20
    ts = prof["columns"]["timestamp"]
    assert ts["sensitive"] is True                      # still suppressed
    assert "categories" not in ts or ts.get("values_suppressed")
    cov = ts["temporal_coverage"]
    assert cov["min_month"] == "2025-03" and cov["max_month"] == "2025-03"
    assert cov["cadence"] in ("~1/15 min", "~1/hour")   # 30-min spacing bucket boundary
    assert cov["n_timestamps"] == 20 * 48
    # subject_id column present and suppressed as identifier
    assert prof["columns"]["subject_id"]["sensitive"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_profile_facets.py -v`
Expected: FAIL with `KeyError: 'subject_key'`

- [ ] **Step 3: Write minimal implementation**

Update `profile_file` (and mirror the same tail logic in `profile_file_chunked`) in `src/gated_cs/profiler/profile.py`. After building `cols` and before the return, attach facets:

```python
# src/gated_cs/profiler/profile.py  (inside profile_file, after `cols` is built)
from .subject_key import detect_subject_key, cohort_n
from .temporal import is_datetime_name, month_bounds, cadence_label

def _attach_facets(df, parsed, cols, thresholds, sample_rows):
    subject_key = detect_subject_key(parsed.header)
    cn = int(cohort_n(df[subject_key])) if subject_key else None
    sid_sample = df[subject_key].head(sample_rows) if subject_key else None
    for name in parsed.header:
        is_dt = is_datetime_name(name)
        if not is_dt:
            # also treat true datetime dtypes as temporal
            if not pd.api.types.is_datetime64_any_dtype(df[name]):
                continue
        ts = pd.to_datetime(df[name], errors="coerce").dropna()
        if ts.empty:
            continue
        cov = month_bounds(ts.min(), ts.max())
        cov["n_timestamps"] = int(ts.shape[0])
        cov["cadence"] = cadence_label(df[name].head(sample_rows), sid_sample)
        cols[name]["temporal_coverage"] = cov
    return subject_key, cn

# then, replacing the return of profile_file:
    sample_rows = sample_rows or thresholds.cadence_sample_rows
    subject_key, cn = _attach_facets(df, parsed, cols, thresholds, sample_rows)
    return {"path": path, "delimiter": parsed.delimiter, "row_count": int(df.shape[0]),
            "file_metadata": parsed.file_metadata, "columns": cols,
            "subject_key": subject_key, "cohort_n": cn}
```

(Per the plan amendment, there is no `profile_file_chunked` — only `profile_file` needs this change.) Add `sample_rows=None` to `profile_file`'s signature.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_profile_facets.py tests/profiler/test_chunked.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/gated_cs/profiler/profile.py tests/profiler/test_profile_facets.py
git commit -m "feat(profiler): attach subject-key, cohort-N, and coarse temporal coverage to file profiles"
```

---

### Task 6: `build()` — recursive discovery, grouping, codebook rendering, timestamped output + manifest

**Files:**
- Modify: `src/gated_cs/profiler/build_dictionary.py`
- Test: `tests/profiler/test_build_time.py`

**Interfaces:**
- Consumes: `discover_files`, `profile_file`, `profile_file_chunked`, `detect_subject_key`, `synthesize`.
- Produces: `build(data_dir, out_dir=None, thresholds=DEFAULTS, id_pool_size=50) -> dict`. When `out_dir` is `None`, writes to `~/claude-time-dictionary/<UTC-timestamp>/` (timestamp passed in / stamped by caller to stay deterministic in tests — accept `out_dir` in tests). Dictionary shape: `{"data_dir", "sources": {source: {relpath: file_profile}}, "files": {relpath: file_profile}}`. Every file is profiled with a single `profile_file` read (no chunking — per the plan amendment). Codebook files get `role: "codebook"` and their descriptive columns rendered in md. Writes `dictionary.json`, `dictionary.md`, `synthetic_samples/<relpath>`, and `run_manifest.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiler/test_build_time.py
import os, json
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.build_dictionary import build

def _mk(tmp_path):
    base = tmp_path / "TIME"
    (base / "oura_ring").mkdir(parents=True)
    (base / "stelo_cgm" / "processed").mkdir(parents=True)
    (base / "stelo_cgm" / "processed" / ".ipynb_checkpoints").mkdir(parents=True)
    (base / "redcap_questionnaires" / "raw").mkdir(parents=True)
    # wearable file
    rows = [{"subject_id": f"S{s:02d}",
             "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(minutes=5 * i),
             "hr": 60 + (i % 30)} for s in range(10) for i in range(30)]
    pd.DataFrame(rows).to_csv(base / "oura_ring" / "TIME_oura_heartrate.csv", index=False)
    # checkpoint dupe that must be ignored
    pd.DataFrame(rows).to_csv(
        base / "stelo_cgm" / "processed" / ".ipynb_checkpoints" / "x-checkpoint.csv", index=False)
    # cgm
    pd.DataFrame(rows).to_csv(base / "stelo_cgm" / "processed" / "TIME_cgm_all_subjects.csv", index=False)
    # codebook
    pd.DataFrame({"field_name": ["q1", "q2"],
                  "question_text": ["How rested?", "How stressed?"]}
                 ).to_csv(base / "redcap_questionnaires" / "raw" / "TIME_redcap_questions.csv", index=False)
    return str(base)

def test_build_groups_by_source_skips_checkpoints_and_writes_manifest(tmp_path):
    data_dir = _mk(tmp_path)
    out = str(tmp_path / "out")
    d = build(data_dir, out_dir=out, thresholds=DEFAULTS)
    # 3 real files, no checkpoint
    assert set(d["sources"].keys()) == {"oura_ring", "stelo_cgm", "redcap_questionnaires"}
    assert len(d["files"]) == 3
    assert not any(".ipynb_checkpoints" in r for r in d["files"])
    # subject key + cohort surfaced
    hr = d["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]
    assert hr["subject_key"] == "subject_id" and hr["cohort_n"] == 10
    assert "temporal_coverage" in hr["columns"]["timestamp"]
    # codebook role + descriptive text surfaced in md
    md = open(os.path.join(out, "dictionary.md")).read()
    assert "How rested?" in md
    # artifacts written
    assert os.path.exists(os.path.join(out, "dictionary.json"))
    assert os.path.exists(os.path.join(out, "run_manifest.json"))
    assert os.path.exists(os.path.join(out, "synthetic_samples",
                                       "oura_ring", "TIME_oura_heartrate.csv"))
    manifest = json.load(open(os.path.join(out, "run_manifest.json")))
    assert manifest["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]["row_count"] == 300
    assert "sha256" in manifest["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]

def test_build_synthetic_samples_leak_nothing_real(tmp_path):
    data_dir = _mk(tmp_path)
    out = str(tmp_path / "out2")
    build(data_dir, out_dir=out, thresholds=DEFAULTS)
    synth = open(os.path.join(out, "synthetic_samples", "oura_ring", "TIME_oura_heartrate.csv")).read()
    # real subject ids look like S00..S09; synthetic id_pool uses SYNTH_ prefix
    assert "S00" not in synth and "SYNTH_" in synth
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_build_time.py -v`
Expected: FAIL (current `build` flat-globs and has no `sources`/manifest)

- [ ] **Step 3: Write minimal implementation**

Rewrite `build` in `src/gated_cs/profiler/build_dictionary.py` (keep `add_layer_to_dictionary`/`profile_dataframe` as-is):

```python
# src/gated_cs/profiler/build_dictionary.py  (new build + helpers)
import glob, hashlib, json, os, subprocess, sys
from .profile import profile_file
from .synthesize import synthesize
from .discover import discover_files
from .subject_key import detect_subject_key
from ..config import DEFAULTS

def _sha256(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(buf), b""):
            h.update(chunk)
    return h.hexdigest()

def _pip_freeze():
    try:
        return subprocess.check_output([sys.executable, "-m", "pip", "freeze"],
                                       text=True).splitlines()
    except Exception:
        return []

def build(data_dir, out_dir=None, thresholds=DEFAULTS, id_pool_size=50):
    if out_dir is None:
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = os.path.join(os.path.expanduser("~"), "claude-time-dictionary", stamp)
    os.makedirs(os.path.join(out_dir, "synthetic_samples"), exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]

    files, sources, manifest_files = {}, {}, {}
    for df_ in discover_files(data_dir):
        size = os.path.getsize(df_.path)
        prof = profile_file(df_.path, thresholds)
        prof["source"], prof["stage"], prof["role"] = df_.source, df_.stage, df_.role
        files[df_.relpath] = prof
        sources.setdefault(df_.source, {})[df_.relpath] = prof
        manifest_files[df_.relpath] = {"sha256": _sha256(df_.path), "bytes": size,
                                       "row_count": prof["row_count"]}
        # synthetic sample (skip codebook — it's reference metadata, not per-person rows)
        if df_.role != "codebook":
            jk = detect_subject_key(list(prof["columns"].keys()))
            synth = synthesize(prof, n_rows=100, seed=0,
                               join_keys=(jk,) if jk else (), id_pool=id_pool)
            dest = os.path.join(out_dir, "synthetic_samples", df_.relpath)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            synth.to_csv(dest, index=False)

    dictionary = {"data_dir": data_dir, "sources": sources, "files": files}
    with open(os.path.join(out_dir, "dictionary.json"), "w") as f:
        json.dump(dictionary, f, indent=2, default=str)
    with open(os.path.join(out_dir, "dictionary.md"), "w") as f:
        f.write(_render_md(dictionary))
    with open(os.path.join(out_dir, "run_manifest.json"), "w") as f:
        json.dump({"data_dir": data_dir,
                   "thresholds": thresholds.__dict__,
                   "files": manifest_files,
                   "packages": _pip_freeze()}, f, indent=2)
    print(f"[claude-time] dictionary written to {out_dir}")
    return dictionary
```

Replace `_render_md` to group by source, show cohort/subject-key, temporal coverage, and codebook text:

```python
def _render_md(d):
    out = ["# TIME_SNAPSHOTS Data Dictionary\n"]
    for source, group in d["sources"].items():
        out.append(f"\n# {source or '(root)'}\n")
        for relpath, prof in group.items():
            hdr = f"\n## {relpath}  ({prof['row_count']} rows"
            if prof.get("cohort_n") is not None:
                hdr += f", {prof['cohort_n']} subjects"
            if prof.get("role") == "codebook":
                hdr += ", role=codebook"
            out.append(hdr + ")\n")
            for meta in prof.get("file_metadata", []):
                out.append(f"> {meta}\n")
            out.append("\n| column | dtype | %missing | cardinality | sensitive | coverage/description |\n")
            out.append("|---|---|---|---|---|---|\n")
            for cname, c in prof["columns"].items():
                cov = c.get("temporal_coverage")
                note = c.get("description", "")
                if cov:
                    note = f"{cov['min_month']}→{cov['max_month']}, {cov['cadence']}" + (
                        f"; {note}" if note else "")
                out.append(f"| {cname} | {c['dtype']} | {c['pct_missing']} | "
                           f"{c['cardinality']} | {c.get('sensitive', False)} | {note} |\n")
    return "".join(out)
```

> **Codebook text in md:** because codebook files are profiled as normal (their `question_text`/`field_name` columns are low-cardinality categoricals under the cap), their category values render in the `categories` of the JSON and their text appears via the standard path. The test asserts `"How rested?"` appears in md — ensure `_render_md` also emits category lists for codebook-role files by appending, for codebook files only, a bullet list of each column's `categories`. Add after the table for `role == "codebook"`:

```python
            if prof.get("role") == "codebook":
                for cname, c in prof["columns"].items():
                    if c.get("categories"):
                        out.append(f"\n**{cname}:** " + "; ".join(c["categories"]) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_build_time.py tests/profiler/test_build_dictionary.py -v`
Expected: PASS (new behavior green; if the legacy `test_build_dictionary.py` asserts the old flat shape, update it to the `sources`/`files` shape in the same commit — note it explicitly.)

- [ ] **Step 5: Commit**

```bash
git add src/gated_cs/profiler/build_dictionary.py tests/profiler/test_build_time.py tests/profiler/test_build_dictionary.py
git commit -m "feat(profiler): build() recursive+grouped dictionary with codebook rendering, timestamped output, run manifest"
```

---

### Task 7: End-to-end leak + k-anon guard on a TIME-shaped fixture tree

**Files:**
- Create: `tests/profiler/test_time_e2e.py`

**Interfaces:**
- Consumes: `build`. No new production code — this is the safety-net acceptance test that locks the isolation invariant.

- [ ] **Step 1: Write the failing test**

```python
# tests/profiler/test_time_e2e.py
import os, json, glob
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.build_dictionary import build

def _mk(tmp_path):
    base = tmp_path / "TIME"
    (base / "oura_ring").mkdir(parents=True)
    (base / "redcap_demographics").mkdir(parents=True)
    rows = [{"subject_id": f"S{s:02d}",
             "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(minutes=5 * i),
             "hr": 60 + (i % 30),
             "SECRET_NOTE": f"note_{s}_{i}"}      # near-unique free text -> must be suppressed
            for s in range(12) for i in range(40)]
    pd.DataFrame(rows).to_csv(base / "oura_ring" / "TIME_oura_heartrate.csv", index=False)
    demo = pd.DataFrame({"subject_id": [f"S{s:02d}" for s in range(12)],
                         "date_of_birth": ["1990-01-01"] * 12,
                         "sex": ["F"] * 6 + ["M"] * 6,
                         "rare_flag": ["common"] * 11 + ["UNIQUE_X"]})  # count<k -> suppressed
    demo.to_csv(base / "redcap_demographics" / "TIME_redcap_demographics.csv", index=False)
    return str(base)

def test_no_raw_values_and_kanon_hold(tmp_path):
    data_dir = _mk(tmp_path)
    out = str(tmp_path / "out")
    build(data_dir, out_dir=out, thresholds=DEFAULTS)

    dict_json = open(os.path.join(out, "dictionary.json")).read()
    all_synth = "".join(open(p).read() for p in
                        glob.glob(os.path.join(out, "synthetic_samples", "**", "*.csv"), recursive=True))
    blob = dict_json + all_synth

    # 1. free-text near-unique values never leak
    assert "SECRET_NOTE" in dict_json          # column name is fine
    assert "note_0_0" not in blob and "note_5_10" not in blob
    # 2. real subject ids never leak (SYNTH_ pool only)
    assert "S00" not in all_synth and "S11" not in all_synth
    # 3. exact DOB never leaks; date column suppressed
    assert "1990-01-01" not in blob
    # 4. rare category (<k) suppressed
    assert "UNIQUE_X" not in blob
    # 5. temporal coverage present but only month-granular
    d = json.load(open(os.path.join(out, "dictionary.json")))
    ts = d["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]["columns"]["timestamp"]
    assert ts["temporal_coverage"]["min_month"] == "2025-01"
    assert "2025-01-01" not in json.dumps(ts)   # no day/second granularity anywhere on the column
```

- [ ] **Step 2: Run test to verify it fails (or passes green if Tasks 1-6 correct)**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler/test_time_e2e.py -v`
Expected: PASS if the pipeline is correct. If any assertion fails, it has found a real leak — fix the responsible module (do not weaken the assertion).

- [ ] **Step 3: Run the full profiler suite**

Run: `cd ~/projects/gated-claude-science && uv run pytest tests/profiler -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/profiler/test_time_e2e.py
git commit -m "test(profiler): end-to-end leak + k-anon acceptance test on TIME-shaped fixtures"
```

---

### Task 8: On-box dry run against real TIME_SNAPSHOTS (metadata-only)

**Files:** none (operational task; produces the actual dictionary set on the box).

**Interfaces:** Consumes the finished `gated_cs.profiler`. This task runs on the data box only; its output stays on the box. Only the run's *printed summary* (paths, counts, and the rendered `dictionary.md`, which is by construction aggregate-only) is reviewed.

- [ ] **Step 1: Sync the code to the box** (into the analyst area, not the data tree)

Run (from desktop): `rsync -av --exclude .git --exclude .venv ~/projects/gated-claude-science/ claude-science-vm:~/gated-cs/`
Expected: files transferred. (Re-point the `claude-science-vm` SSH alias to the current session IP first — IPs are ephemeral.)

- [ ] **Step 2: Install into the gate venv on the box**

Run: `ssh claude-science-vm 'cd ~/gated-cs && python -m pip install -e . && python -c "import gated_cs; print(\"ok\")"'`
Expected: `ok`

- [ ] **Step 3: Build the dictionary on the box (default timestamped output)**

Run: `ssh claude-science-vm 'cd ~/gated-cs && python -m gated_cs.profiler.build_dictionary "/procedure/data/local_data/TIME_SNAPSHOTS"'`
Expected: prints `[claude-time] dictionary written to ~/claude-time-dictionary/<UTC-timestamp>/`

- [ ] **Step 4: Review ONLY aggregate output (no raw reads)**

Run: `ssh claude-science-vm 'D=$(ls -dt ~/claude-time-dictionary/*/ | head -1); echo "$D"; sed -n "1,120p" "$D/dictionary.md"; echo "--- manifest sources ---"; python -c "import json,sys; m=json.load(open(sys.argv[1])); print(len(m[\"files\"]), \"files\"); print(list({v for k,v in [(k, k.split(\"/\")[0]) for k in m[\"files\"]]}))" "$D/run_manifest.json"'`
Expected: dictionary shows all ~43 files grouped by device, each with cohort-N, per-column sensitivity, temporal coverage on datetime columns; no raw row values present.

- [ ] **Step 5: Sanity-check the invariant on the box**

Run: `ssh claude-science-vm 'D=$(ls -dt ~/claude-time-dictionary/*/ | head -1); grep -RlEi "SYNTH_" "$D/synthetic_samples" | head -1 && echo "synthetic ids present"; echo "spot-check: no source subject-id column values should appear in dictionary.json"'`
Expected: synthetic ids present; reviewer confirms `dictionary.md`/`dictionary.json` carry only aggregates. **Do not** `cat` any file under `/procedure/data/local_data/`.

- [ ] **Step 6: Record the run**

Note the output dir + manifest content-hashes in the session summary and the `project_claude_time_dictionary` memory. Do not commit any real data or real dictionary output to the repo (repo stays code + synthetic-fixture tests only).

---

## Self-Review

**1. Spec coverage:**
- §1 recursive discovery/grouping → Task 1 + Task 6. ✓
- §2 configurable/auto-detected subject key + cohort-N → Task 2 + Task 5. ✓
- §3 large-file handling → Task 4, amended: chunking dropped (see Plan amendment); single whole-file read, k-anon on full counts. Memory verified on box in Task 8. ✓
- §4 coarse temporal coverage → Task 3 + Task 5. ✓
- §5 reference-codebook handling → Task 1 (tagging) + Task 6 (rendering, synthesis skip). ✓
- §6 timestamped output + run manifest → Task 6. ✓
- §7 testing (leak, k-anon, chunk equivalence, temporal coarseness, codebook, join key) → Tasks 1–7. ✓
- On-box run → Task 8. ✓
- SDC core unchanged → verified: `sensitivity.py`, k-anon in `profile_column`, `_nice_step`, synthesize semantics are not modified (only `_histogram` is refactored to call `_nice_edges`, behavior-preserving, guarded by the existing `test_profile.py` + Task 4 equivalence test).

**2. Placeholder scan:** No TBD/TODO; every code step carries runnable code; the one "future streaming" note in Task 4 is explicitly deferred with the interface seam in place, not a gap in this plan's deliverable.

**3. Type consistency:** `detect_subject_key`/`cohort_n` (Task 2) used identically in Tasks 5 & 6; `profile_file`/`profile_file_chunked` return the same dict shape (Tasks 4–5) consumed by `build` (Task 6); `temporal_coverage` dict keys (`min_month`,`max_month`,`n_timestamps`,`cadence`) are consistent across Tasks 3, 5, 6, 7; `DiscoveredFile` fields (Task 1) consumed by `build` (Task 6) match.

**Note on legacy tests:** Task 6 may require updating `tests/profiler/test_build_dictionary.py` from the old flat `{"files": {...}}` shape to the new `{"sources","files"}` shape — flagged in Task 6 Step 4 and included in its commit.
