# Derived-Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the gated TRE so `submit-derivation` computes per-person derived features, persists them inside the PHI boundary (`/var/gate/derived/`, cs-exec-only), and auto-profiles them into the dictionary/synthetic for reuse — while only aggregates leave via the existing gate.

**Architecture:** One shared executor (`run_analysis.py`) gains two optional binds — a read-only `DERIVED_DIR` (both verbs, so analyses reuse layers) and a writable `LAYER_DIR` (derivations only, persisted un-gate-checked, never delivered). A new `gate/derive.py` module validates the layer, writes an executor-authored provenance manifest, and incrementally profiles the layer into the dictionary/synthetic. New provision artifacts (`run-derivation` wrapper, `submit-derivation` command, second sudoers rule) expose the verb.

**Tech Stack:** Python 3.10, pandas/numpy/scikit-learn (gate venv `/opt/gated-cs`), bubblewrap, pytest, parquet (pyarrow) or gzip-TSV.

## Global Constraints

- Isolation invariant: exactly one identity (`cs-exec`) reads real per-person data (raw OR derived); every path out passes through `check_table` SDC (`k=5`, `row_cap=20`).
- `/var/gate/derived/` is `cs-exec:cs-exec` mode **0700** — NOT the `csbridge` group; `cs-gated` can never read it.
- `LAYER_DIR` contents persist to the store un-gate-checked and are NEVER delivered to `cs-gated`; `OUTPUT_DIR` contents are always gate-checked.
- Provenance is written by the executor (`cs-exec`), never by the untrusted child.
- Only `submit-derivation` can create a layer; `submit-analysis` behavior is unchanged except it gains the read-only `DERIVED_DIR` mount.
- Reuse existing modules/patterns; join key is `public_client_id`; synthetic uses the shared `SYNTH_%04d` id pool.
- Tests run without bwrap by setting `GATED_CS_NO_SANDBOX=1` (as the existing suite does).
- **Do NOT commit or push unless the user asks.** Commit *messages* are drafted in steps for convenience, but execution pauses for user consent; changes route through a PR branch, never the default branch.

## File Structure

- `src/gated_cs/gate/run_analysis.py` — MODIFY: `_child_command` + `run()` gain `derived_dir`/`layer_dir` binds; `run()` calls `derive.persist_layer` in derivation mode; `main()` gains `--derived-dir`/`--layer-dir`/`--layer-name`.
- `src/gated_cs/gate/derive.py` — CREATE: `persist_layer()` (validate + move to store), `write_manifest()` (+ append provenance), `read_layer_frame()` helper.
- `src/gated_cs/profiler/build_dictionary.py` — MODIFY: add `profile_dataframe()` and `add_layer_to_dictionary()` (incremental merge + one synthetic file, tag `derived`).
- `provision/run-derivation-wrapper` — CREATE: cs-exec wrapper pinning `DATA_DIR`, `DERIVED_DIR`, a fresh `LAYER_DIR`, mode.
- `provision/submit-derivation` — CREATE: cs-gated entrypoint (mirror `submit-analysis`).
- `provision/sudoers.d/cs-gated` — MODIFY: add second NOPASSWD rule for `/opt/gate/run-derivation`.
- `provision/provision.sh` — MODIFY: create `/var/gate/derived`, install the two new scripts.
- `tests/gate/test_derivation.py` — CREATE: executor derivation-mode + persistence + manifest tests.
- `tests/gate/test_redteam_derivation.py` — CREATE: adversarial isolation tests.
- `tests/profiler/test_add_layer.py` — CREATE: incremental profiling/synthetic tests.
- `analyses/` exemplar (`impute.py`) is delivered as a doc artifact in Task 8, not repo code.

---

### Task 1: Derived store read-side bind (both verbs can reuse layers)

**Files:**
- Modify: `src/gated_cs/gate/run_analysis.py` (`_child_command`, `run`)
- Test: `tests/gate/test_derivation.py`

**Interfaces:**
- Produces: `_child_command(script_path, data_dir, out_dir, derived_dir=None, layer_dir=None)`; `run(..., derived_dir=None, layer_dir=None, layer_name=None, ...)`. `DERIVED_DIR` env visible to the child when `derived_dir` is set.

- [ ] **Step 1: Write the failing test**
```python
# tests/gate/test_derivation.py
import os, pandas as pd
from gated_cs.gate.run_analysis import run

def _write(p, s): open(p, "w").write(s); return p

def test_analysis_can_read_derived_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX", "1")
    data = tmp_path/"data"; data.mkdir()
    derived = tmp_path/"derived"; derived.mkdir()
    (derived/"layerX").mkdir()
    pd.DataFrame({"public_client_id":["SYNTH_0001"],"score":[1.0]}).to_csv(derived/"layerX"/"data.csv", index=False)
    out = tmp_path/"out"; q = tmp_path/"q"; res = tmp_path/"res"; audit = tmp_path/"a.jsonl"
    script = _write(str(tmp_path/"s.py"),
        "import os,glob,pandas as pd\n"
        "p=glob.glob(os.path.join(os.environ['DERIVED_DIR'],'layerX','data.*'))[0]\n"
        "n=len(pd.read_csv(p))\n"
        "pd.DataFrame({'metric':['rows'],'value':[n]}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'),index=False)\n")
    r = run(script, str(data), str(out), str(audit), str(q), results_dir=str(res), derived_dir=str(derived))
    assert r["status"] == "released"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `cd ~/projects/gated-claude-science && .venv/bin/pytest tests/gate/test_derivation.py::test_analysis_can_read_derived_dir -v`
Expected: FAIL — `run()` has no `derived_dir` kwarg (TypeError).

- [ ] **Step 3: Implement the read-side bind**
In `_child_command` add the parameter and, inside the sandbox branch, after the `data_dir` ro-bind:
```python
def _child_command(script_path, data_dir, out_dir, derived_dir=None, layer_dir=None):
    ...
    cmd = [ ... existing through "--ro-bind", script_path, script_path, ... ]
    if derived_dir:
        cmd += ["--ro-bind-try", derived_dir, derived_dir, "--setenv", "DERIVED_DIR", derived_dir]
    if layer_dir:
        cmd += ["--bind", layer_dir, layer_dir, "--setenv", "LAYER_DIR", layer_dir]
    cmd += ["--bind", out_dir, out_dir, "--setenv", "OUTPUT_DIR", out_dir,
            "--setenv", "DATA_DIR", data_dir, "--setenv", "PATH", os.environ.get("PATH","/usr/bin:/bin"),
            "--setenv", "HOME", "/tmp", py, script_path]
    return cmd
```
For the no-sandbox fallback, return `[py, script_path]` unchanged (env passed by `run()` — see below). In `run()` add kwargs and thread env + command:
```python
def run(script_path, data_dir, out_dir, audit_path, queue_dir, results_dir=None,
        derived_dir=None, layer_dir=None, layer_name=None, thresholds=DEFAULTS):
    ...
    env = {"OUTPUT_DIR": out_dir, "DATA_DIR": data_dir, "PATH": os.environ.get("PATH",""), "HOME": out_dir}
    if derived_dir: env["DERIVED_DIR"] = derived_dir
    if layer_dir:   env["LAYER_DIR"] = layer_dir
    ...
    cmd = _child_command(script_path, data_dir, out_dir, derived_dir=derived_dir, layer_dir=layer_dir)
```

- [ ] **Step 4: Run test to verify it passes**
Run: `.venv/bin/pytest tests/gate/test_derivation.py::test_analysis_can_read_derived_dir -v`
Expected: PASS.

- [ ] **Step 5: Regression + commit**
Run: `.venv/bin/pytest tests/gate/ -q` (all existing gate tests still pass — the new kwargs are optional).
```bash
git add src/gated_cs/gate/run_analysis.py tests/gate/test_derivation.py
git commit -m "feat(gate): read-only DERIVED_DIR bind so analyses can reuse derived layers"
```

---

### Task 2: `derive.py` — validate + persist a layer, executor-authored provenance

**Files:**
- Create: `src/gated_cs/gate/derive.py`
- Test: `tests/gate/test_derivation.py` (append)

**Interfaces:**
- Produces:
  - `persist_layer(layer_stage_dir, store_dir, name, *, script_path, data_dir, derived_dir, params, fit_quality) -> dict` — validates the staged matrix (readable, has `public_client_id`, ≥1 row), moves it to `store_dir/name/`, writes `MANIFEST.json`, appends `PROVENANCE.jsonl`, returns the manifest dict. Raises `DerivationError` on invalid layer.
  - `read_layer_frame(path) -> pd.DataFrame` — reads `data.parquet` (pyarrow) or `data.tsv.gz`.
- Consumes: `_hash` from `run_analysis` (script/content hashing).

- [ ] **Step 1: Write the failing test**
```python
# tests/gate/test_derivation.py (append)
import json
from gated_cs.gate.derive import persist_layer, DerivationError

def _stage_matrix(d, ids=("SYNTH_0001","SYNTH_0002")):
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"public_client_id":list(ids),"score":[1.0,2.0]}).to_csv(d/"data.tsv.gz", sep="\t", index=False, compression="gzip")

def test_persist_layer_writes_manifest_and_moves(tmp_path):
    stage = tmp_path/"stage"; _stage_matrix(stage)
    store = tmp_path/"store"; store.mkdir()
    script = tmp_path/"s.py"; script.write_text("print(1)")
    m = persist_layer(str(stage), str(store), "layerX", script_path=str(script),
                      data_dir=str(tmp_path/"data"), derived_dir=None,
                      params={"seed":0}, fit_quality={"cv_r2":0.45})
    assert (store/"layerX"/"MANIFEST.json").exists()
    man = json.loads((store/"layerX"/"MANIFEST.json").read_text())
    assert man["name"]=="layerX" and man["fit_quality"]["cv_r2"]==0.45
    assert "script_hash" in man and "data_hash" in man and "created_utc" in man
    assert (store/"layerX"/"PROVENANCE.jsonl").exists()

def test_persist_layer_rejects_missing_join_key(tmp_path):
    stage = tmp_path/"stage"; stage.mkdir()
    pd.DataFrame({"nope":[1,2]}).to_csv(stage/"data.tsv.gz", sep="\t", index=False, compression="gzip")
    store = tmp_path/"store"; store.mkdir(); s = tmp_path/"s.py"; s.write_text("x")
    try:
        persist_layer(str(stage), str(store), "bad", script_path=str(s), data_dir="d",
                      derived_dir=None, params={}, fit_quality={})
        assert False, "should reject"
    except DerivationError:
        pass
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/pytest tests/gate/test_derivation.py -k persist_layer -v`
Expected: FAIL — module `gated_cs.gate.derive` does not exist.

- [ ] **Step 3: Implement `derive.py`**
```python
# src/gated_cs/gate/derive.py
import hashlib, json, os, shutil, glob
from datetime import datetime, timezone
import pandas as pd

class DerivationError(Exception): pass

JOIN_KEY = "public_client_id"

def _sha_file(path):
    with open(path, "rb") as f: return hashlib.sha256(f.read()).hexdigest()[:16]

def read_layer_frame(path):
    if path.endswith(".parquet"): return pd.read_parquet(path)
    return pd.read_csv(path, sep="\t", low_memory=False)

def _stage_data_file(stage_dir):
    hits = sorted(glob.glob(os.path.join(stage_dir, "data.*")))
    if not hits: raise DerivationError("no data.* written to LAYER_DIR")
    return hits[0]

def _venv_versions():
    import pandas, numpy
    v = {"pandas": pandas.__version__, "numpy": numpy.__version__}
    for mod in ("sklearn", "scipy", "statsmodels"):
        try: v[mod] = __import__(mod).__version__
        except Exception: v[mod] = None
    return v

def persist_layer(layer_stage_dir, store_dir, name, *, script_path, data_dir,
                  derived_dir, params, fit_quality):
    src = _stage_data_file(layer_stage_dir)
    df = read_layer_frame(src)
    if JOIN_KEY not in df.columns:
        raise DerivationError(f"derived matrix missing join key {JOIN_KEY!r}")
    if len(df) == 0:
        raise DerivationError("derived matrix is empty")
    dest = os.path.join(store_dir, name); os.makedirs(dest, exist_ok=True)
    dest_data = os.path.join(dest, os.path.basename(src))
    shutil.move(src, dest_data)
    for extra in glob.glob(os.path.join(layer_stage_dir, "model.*")):
        shutil.move(extra, os.path.join(dest, os.path.basename(extra)))
    manifest = {
        "name": name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "script_hash": _sha_file(script_path),
        "data_hash": _sha_file(dest_data),
        "data_file": os.path.basename(dest_data),
        "inputs": {"data_dir": data_dir, "derived_dir": derived_dir},
        "params": params, "venv": _venv_versions(),
        "schema": {c: str(t) for c, t in df.dtypes.astype(str).items()},
        "n_persons": int(df[JOIN_KEY].nunique()), "n_rows": int(len(df)),
        "fit_quality": fit_quality,
    }
    with open(os.path.join(dest, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    with open(os.path.join(dest, "PROVENANCE.jsonl"), "a") as f:
        f.write(json.dumps(manifest) + "\n")
    return manifest
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/pytest tests/gate/test_derivation.py -k persist_layer -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add src/gated_cs/gate/derive.py tests/gate/test_derivation.py
git commit -m "feat(gate): derive.persist_layer with executor-authored provenance manifest"
```

---

### Task 3: Executor derivation mode (LAYER_DIR writable, persisted, never delivered)

**Files:**
- Modify: `src/gated_cs/gate/run_analysis.py` (`run`, `main`)
- Test: `tests/gate/test_derivation.py` (append)

**Interfaces:**
- Consumes: `derive.persist_layer`. Produces: `run(..., layer_dir=..., layer_name=...)` persists the layer after a clean child exit; `OUTPUT_DIR` is still gate-checked and delivered; audit gets a `derivation` verdict. `main()` accepts `--derived-dir`, `--layer-dir`, `--layer-name`, `--store` (default `/var/gate/derived`).

- [ ] **Step 1: Write the failing test**
```python
# tests/gate/test_derivation.py (append)
def test_derivation_persists_layer_and_releases_quality(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX", "1")
    data = tmp_path/"data"; data.mkdir()
    store = tmp_path/"store"; store.mkdir()
    out = tmp_path/"out"; q = tmp_path/"q"; res = tmp_path/"res"; audit = tmp_path/"a.jsonl"
    script = str(tmp_path/"d.py")
    open(script,"w").write(
        "import os,pandas as pd\n"
        "df=pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(10)],'imp':[float(i) for i in range(10)]})\n"
        "df.to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        "pd.DataFrame({'metric':['cv_r2'],'value':[0.45]}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'quality.csv'),index=False)\n")
    r = run(script, str(data), str(out), str(audit), str(q), results_dir=str(res),
            layer_dir=str(tmp_path/"stage"), layer_name="imp_layer",
            derived_dir=str(store))
    assert r["status"] == "released"                       # quality aggregate released
    assert (store/"imp_layer"/"MANIFEST.json").exists()    # layer persisted
    import json
    verdicts = [json.loads(l)["verdict"] for l in open(audit)]
    assert "derivation" in verdicts
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/pytest tests/gate/test_derivation.py -k derivation_persists -v`
Expected: FAIL — `run()` ignores `layer_dir`; no MANIFEST, no `derivation` verdict.

- [ ] **Step 3: Implement derivation mode in `run()`**
Before the artifact loop, ensure the stage dir exists: `if layer_dir: os.makedirs(layer_dir, exist_ok=True)`. After the child returns 0 and BEFORE returning, when `layer_dir and layer_name`:
```python
    from .derive import persist_layer, DerivationError
    ...
    if layer_dir and layer_name and results_dir is not None:
        store_dir = derived_dir or os.path.dirname(layer_dir)
        try:
            man = persist_layer(layer_dir, store_dir, layer_name, script_path=script_path,
                                data_dir=data_dir, derived_dir=derived_dir, params={},
                                fit_quality={"released_aggregates": len(released)})
            audit.record({"script_hash": sh, "verdict": "derivation", "layer": layer_name,
                          "n_persons": man["n_persons"], "data_hash": man["data_hash"]})
        except DerivationError as e:
            audit.record({"script_hash": sh, "verdict": "derivation_rejected", "reason": scrub(str(e))})
```
(The `OUTPUT_DIR` gate-check loop is unchanged; `LAYER_DIR` is never walked by `_iter_artifacts`, so its contents are never gate-checked or delivered.) Extend `main()`:
```python
    ap.add_argument("--derived-dir", default=None)
    ap.add_argument("--layer-dir", default=None)
    ap.add_argument("--layer-name", default=None)
    ...
    r = run(a.script, a.data_dir, a.out_dir, a.audit, a.queue, results_dir=a.results,
            derived_dir=a.derived_dir, layer_dir=a.layer_dir, layer_name=a.layer_name)
```

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/pytest tests/gate/test_derivation.py -k derivation_persists -v` then `.venv/bin/pytest tests/gate/ -q`
Expected: PASS; existing gate tests unaffected.

- [ ] **Step 5: Commit**
```bash
git add src/gated_cs/gate/run_analysis.py tests/gate/test_derivation.py
git commit -m "feat(gate): derivation mode — persist LAYER_DIR to store, release only OUTPUT_DIR"
```

---

### Task 4: Incremental dictionary + synthetic extension for a layer

**Files:**
- Modify: `src/gated_cs/profiler/build_dictionary.py` (add `profile_dataframe`, `add_layer_to_dictionary`)
- Test: `tests/profiler/test_add_layer.py`

**Interfaces:**
- Consumes: `profile_column` (per-column), `synthesize`. Produces:
  - `profile_dataframe(df, thresholds=DEFAULTS) -> dict` — `{row_count, file_metadata:[], columns:{...}}` (same shape as `profile_file` output, minus path/delimiter).
  - `add_layer_to_dictionary(dict_path, out_dir, name, df, thresholds=DEFAULTS, join_keys=("public_client_id",), id_pool_size=50) -> dict` — profiles `df`, tags the file entry `{"derived": True}`, merges into `dictionary.json` (+ re-renders `dictionary.md`), and writes one synthetic file `out_dir/synthetic_samples/<name>.csv` on the shared `SYNTH_` pool.

- [ ] **Step 1: Write the failing test**
```python
# tests/profiler/test_add_layer.py
import json, os, pandas as pd
from gated_cs.profiler.build_dictionary import build, add_layer_to_dictionary

def test_add_layer_merges_and_tags_derived(tmp_path):
    data = tmp_path/"data"; data.mkdir()
    pd.DataFrame({"public_client_id":["SYNTH_0001","SYNTH_0002"],"glucose":[90,95]}).to_csv(data/"chem.csv", index=False)
    out = tmp_path/"dict"; build(str(data), str(out))
    layer = pd.DataFrame({"public_client_id":["SYNTH_0001","SYNTH_0002"],"imp":[1.0,2.0]})
    add_layer_to_dictionary(str(out/"dictionary.json"), str(out), "metabolomics_imputed", layer)
    d = json.loads((out/"dictionary.json").read_text())
    assert "metabolomics_imputed" in d["files"]
    assert d["files"]["metabolomics_imputed"]["derived"] is True
    assert (out/"synthetic_samples"/"metabolomics_imputed.csv").exists()
    syn = pd.read_csv(out/"synthetic_samples"/"metabolomics_imputed.csv")
    assert syn["public_client_id"].str.startswith("SYNTH_").all()   # shared pool -> joinable
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/pytest tests/profiler/test_add_layer.py -v`
Expected: FAIL — `add_layer_to_dictionary` not defined.

- [ ] **Step 3: Implement**
```python
# build_dictionary.py (append)
from .profile import profile_column   # add to imports

def profile_dataframe(df, thresholds=DEFAULTS):
    cols = {name: profile_column(df[name], name=name, thresholds=thresholds) for name in df.columns}
    return {"file_metadata": [], "row_count": int(df.shape[0]), "columns": cols}

def add_layer_to_dictionary(dict_path, out_dir, name, df, thresholds=DEFAULTS,
                            join_keys=("public_client_id",), id_pool_size=50):
    with open(dict_path) as f: d = json.load(f)
    prof = profile_dataframe(df, thresholds); prof["derived"] = True
    d["files"][name] = prof
    with open(dict_path, "w") as f: json.dump(d, f, indent=2)
    with open(os.path.join(os.path.dirname(dict_path), "dictionary.md"), "w") as f:
        f.write(_render_md(d))
    ss = os.path.join(out_dir, "synthetic_samples"); os.makedirs(ss, exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    synth = synthesize(prof, n_rows=100, seed=0, join_keys=join_keys, id_pool=id_pool)
    synth.to_csv(os.path.join(ss, name if name.endswith(".csv") else name + ".csv"), index=False)
    return prof
```
(`_render_md` already tolerates entries whose `file_metadata` is empty.)

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/pytest tests/profiler/test_add_layer.py -v` then `.venv/bin/pytest tests/profiler/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add src/gated_cs/profiler/build_dictionary.py tests/profiler/test_add_layer.py
git commit -m "feat(profiler): incrementally profile a derived layer into dictionary+synthetic (tagged derived)"
```

---

### Task 5: Wire auto-profiling into derivation mode + sensitivity screening

**Files:**
- Modify: `src/gated_cs/gate/run_analysis.py` (call `add_layer_to_dictionary` after persist)
- Test: `tests/gate/test_derivation.py` (append)

**Interfaces:**
- Consumes: `derive.read_layer_frame`, `build_dictionary.add_layer_to_dictionary`. Produces: after a successful derivation, if a dictionary exists at `--dict` (new optional arg, default `/var/gate/dict/dictionary.json`), the layer is profiled into it; identifier/date-like derived columns are suppressed by the existing `is_sensitive` path (inherited via `profile_column`).

- [ ] **Step 1: Write the failing test** (sensitivity inherited + auto-profile)
```python
# tests/gate/test_derivation.py (append)
def test_derivation_autoprofiles_and_screens_sensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX", "1")
    data = tmp_path/"data"; data.mkdir()
    dictdir = tmp_path/"dict"; 
    from gated_cs.profiler.build_dictionary import build
    (data/"chem.csv").write_text("public_client_id,glucose\nSYNTH_0001,90\nSYNTH_0002,95\n")
    build(str(data), str(dictdir))
    store = tmp_path/"store"; store.mkdir()
    out=tmp_path/"o"; q=tmp_path/"q"; res=tmp_path/"r"; audit=tmp_path/"a.jsonl"
    script=str(tmp_path/"d.py")
    open(script,"w").write(
        "import os,pandas as pd\n"
        "df=pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(8)],"
        "'imp':[float(i) for i in range(8)],'birth_date':['1980-01-01']*8})\n"
        "df.to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        "pd.DataFrame({'metric':['cv_r2'],'value':[0.5]}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'q.csv'),index=False)\n")
    run(script,str(data),str(out),str(audit),str(q),results_dir=str(res),
        layer_dir=str(tmp_path/"stage"),layer_name="imp_layer",derived_dir=str(store),
        dict_path=str(dictdir/"dictionary.json"))
    import json; d=json.loads((dictdir/"dictionary.json").read_text())
    assert d["files"]["imp_layer"]["derived"] is True
    assert d["files"]["imp_layer"]["columns"]["birth_date"]["sensitive"] is True  # re-encoded date screened
```

- [ ] **Step 2: Run to verify it fails**
Run: `.venv/bin/pytest tests/gate/test_derivation.py -k autoprofiles -v`
Expected: FAIL — `run()` has no `dict_path`; layer not profiled.

- [ ] **Step 3: Implement** — add `dict_path=None` to `run()` and, right after the successful `persist_layer` call:
```python
            if dict_path and os.path.exists(dict_path):
                from ..profiler.build_dictionary import add_layer_to_dictionary
                from .derive import read_layer_frame
                dfl = read_layer_frame(os.path.join(store_dir, layer_name, man["data_file"]))
                add_layer_to_dictionary(dict_path, os.path.dirname(dict_path), layer_name, dfl)
```
Add `--dict` to `main()` (default `/var/gate/dict/dictionary.json`) and pass `dict_path=a.dict`.

- [ ] **Step 4: Run to verify it passes**
Run: `.venv/bin/pytest tests/gate/test_derivation.py -k autoprofiles -v`
Expected: PASS (birth_date flagged sensitive via existing `is_sensitive`).

- [ ] **Step 5: Commit**
```bash
git add src/gated_cs/gate/run_analysis.py tests/gate/test_derivation.py
git commit -m "feat(gate): auto-profile derived layer into dictionary; sensitivity screening inherited"
```

---

### Task 6: Adversarial isolation tests (the load-bearing guarantees)

**Files:**
- Create: `tests/gate/test_redteam_derivation.py`

**Interfaces:** Consumes `run`, `derive.persist_layer`. No new production code — this task proves the boundary and may only add a small guard if a test fails.

- [ ] **Step 1: Write the tests**
```python
# tests/gate/test_redteam_derivation.py
import json, os, pandas as pd
from gated_cs.gate.run_analysis import run

def _base(tmp_path):
    for n in ("data","store","out","q","res"): (tmp_path/n).mkdir()
    return (str(tmp_path/"data"), str(tmp_path/"store"), str(tmp_path/"out"),
            str(tmp_path/"q"), str(tmp_path/"res"), str(tmp_path/"a.jsonl"))

def test_rows_to_output_still_quarantined_in_derivation(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX","1")
    data,store,out,q,res,audit=_base(tmp_path); s=str(tmp_path/"d.py")
    open(s,"w").write(
        "import os,pandas as pd\n"
        "pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(5)],'v':range(5)})"
        ".to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        # a 100-row dump to OUTPUT_DIR must be quarantined by the gate
        "pd.DataFrame({'x':range(100)}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'dump.csv'),index=False)\n")
    r=run(s,data,out,audit,q,results_dir=res,layer_dir=str(tmp_path/"stg"),layer_name="L",derived_dir=store)
    assert r["status"]=="queued"                              # dump did NOT release
    assert os.listdir(res)==[] or all("dump" not in f for f in os.listdir(res))

def test_layer_dir_rows_persist_but_are_not_delivered(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX","1")
    data,store,out,q,res,audit=_base(tmp_path); s=str(tmp_path/"d.py")
    open(s,"w").write(
        "import os,pandas as pd\n"
        # write 500 raw-looking rows to the STORE (LAYER_DIR)
        "pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(500)],'raw':range(500)})"
        ".to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n")
    run(s,data,out,audit,q,results_dir=res,layer_dir=str(tmp_path/"stg"),layer_name="L",derived_dir=store)
    # persisted in the store...
    assert os.path.exists(os.path.join(store,"L","MANIFEST.json"))
    # ...but NOTHING delivered to results/ (the only cs-gated-readable path)
    assert os.listdir(res)==[]

def test_child_cannot_forge_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX","1")
    data,store,out,q,res,audit=_base(tmp_path); s=str(tmp_path/"d.py")
    open(s,"w").write(
        "import os,pandas as pd\n"
        "d=os.environ['LAYER_DIR']\n"
        "pd.DataFrame({'public_client_id':['SYNTH_0001'],'v':[1]}).to_csv(os.path.join(d,'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        "open(os.path.join(d,'MANIFEST.json'),'w').write('{\"forged\":true}')\n")
    run(s,data,out,audit,q,results_dir=res,layer_dir=str(tmp_path/"stg"),layer_name="L",derived_dir=store)
    man=json.loads(open(os.path.join(store,"L","MANIFEST.json")).read())
    assert "forged" not in man and man["name"]=="L"          # executor's manifest wins
```

- [ ] **Step 2: Run**
Run: `.venv/bin/pytest tests/gate/test_redteam_derivation.py -v`
Expected: the forge test may FAIL if `persist_layer` copies the child's `MANIFEST.json` — it must not (it only moves `data.*`/`model.*`). If it fails, ensure `_stage_data_file` selects only `data.*` and `persist_layer` writes its own `MANIFEST.json` last (overwriting any child file). Re-run to PASS.

- [ ] **Step 3: (If needed) guard, then commit**
```bash
git add tests/gate/test_redteam_derivation.py src/gated_cs/gate/derive.py
git commit -m "test(gate): adversarial isolation for the derived store (no exfil, no forged provenance)"
```

- [ ] **Step 4: OS-level isolation note (verified at provision time, not in pytest):** `/var/gate/derived` is `0700 cs-exec`; add a RUNBOOK check `sudo -u cs-gated ls /var/gate/derived` → must be **Permission denied**. Recorded in Task 7.

---

### Task 7: Provision — store, wrappers, command, sudoers

**Files:**
- Create: `provision/run-derivation-wrapper`, `provision/submit-derivation`
- Modify: `provision/sudoers.d/cs-gated`, `provision/provision.sh`
- Test: `tests/test_bridge_files.py` (append static checks)

**Interfaces:** Produces the `submit-derivation <script.py> --layer <name>` entrypoint and the cs-exec `run-derivation` wrapper pinning trusted paths.

- [ ] **Step 1: Write `provision/run-derivation-wrapper`**
```bash
#!/usr/bin/env bash
# installed at /opt/gate/run-derivation (root:cs-exec, 0750). Runs as cs-exec.
set -euo pipefail
SCRIPT="$1"; LAYER="$2"                        # $2 = --layer value (validated by submit-derivation)
DATA_DIR=/data/arivale
DERIVED_DIR=/var/gate/derived
OUT_DIR="$(mktemp -d /var/gate/out.XXXXXX)"
LAYER_DIR="$(mktemp -d /var/gate/layerstage.XXXXXX)"
exec env -i PATH=/opt/gated-cs/bin:/usr/local/bin:/usr/bin:/bin GATED_CS_REQUIRE_SANDBOX=1 \
  run-analysis "$SCRIPT" --data-dir "$DATA_DIR" --out-dir "$OUT_DIR" \
    --audit /var/gate/audit.jsonl --queue /var/gate/queue --results /var/gate/results \
    --derived-dir "$DERIVED_DIR" --layer-dir "$LAYER_DIR" --layer-name "$LAYER" \
    --dict /var/gate/dict/dictionary.json
```

- [ ] **Step 2: Write `provision/submit-derivation`**
```bash
#!/usr/bin/env bash
set -euo pipefail
[ $# -eq 3 ] && [ "$2" = "--layer" ] || { echo "usage: submit-derivation <script.py> --layer <name>" >&2; exit 2; }
case "$3" in *[!a-zA-Z0-9_-]*) echo "layer name must be [A-Za-z0-9_-]" >&2; exit 2;; esac
src="$(realpath "$1")"; dest="/var/gate/incoming/$(id -un)-$$-$(basename "$src")"
cp -- "$src" "$dest"; chmod 0640 "$dest"
exec sudo -u cs-exec /opt/gate/run-derivation "$dest" "$3"
```

- [ ] **Step 3: Update sudoers + provision.sh**
`provision/sudoers.d/cs-gated` (append):
```
cs-gated ALL=(cs-exec) NOPASSWD: /opt/gate/run-derivation
```
`provision/provision.sh` — after the `/var/gate/results` block add:
```bash
mkdir -p /var/gate/derived
chown cs-exec:cs-exec /var/gate/derived; chmod 0700 /var/gate/derived   # derived store: cs-exec ONLY
```
and in the install block:
```bash
install -m 0755 "$SRC/provision/submit-derivation" /usr/local/bin/submit-derivation
install -o root -g cs-exec -m 0750 "$SRC/provision/run-derivation-wrapper" /opt/gate/run-derivation
```

- [ ] **Step 4: Static test** (mirror `tests/test_bridge_files.py`)
```python
def test_submit_derivation_validates_layer_name():
    import subprocess, sys
    p = subprocess.run(["bash", "provision/submit-derivation", "x.py", "--layer", "bad;name"],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "layer name" in p.stderr
```
Run: `.venv/bin/pytest tests/test_bridge_files.py -q` → PASS.

- [ ] **Step 5: Commit**
```bash
git add provision/run-derivation-wrapper provision/submit-derivation provision/sudoers.d/cs-gated provision/provision.sh tests/test_bridge_files.py
git commit -m "feat(provision): submit-derivation verb, run-derivation wrapper, 0700 derived store, sudoers rule"
```

---

### Task 8: Metabolomics imputation exemplar (analyst-facing derivation script)

**Files:**
- Create: `docs/examples/impute-metabolomics.py` (a template the operator drops into `analyses/NN-impute-metabolomics/` on the VM)

**Interfaces:** Consumes `DATA_DIR`, `LAYER_DIR`, `OUTPUT_DIR`. Produces `data.tsv.gz` (imputed matrix) in `LAYER_DIR` + `*.csv` fit-quality in `OUTPUT_DIR`.

- [ ] **Step 1: Write the exemplar script**
```python
# docs/examples/impute-metabolomics.py — run via: submit-derivation impute-metabolomics.py --layer metabolomics_imputed
import os, numpy as np, pandas as pd
from sklearn.experimental import enable_iterative_imputer  # noqa
from sklearn.impute import IterativeImputer

DATA_DIR, LAYER_DIR, OUTPUT_DIR = os.environ["DATA_DIR"], os.environ["LAYER_DIR"], os.environ["OUTPUT_DIR"]
df = pd.read_csv(os.path.join(DATA_DIR, "metabolomics_corrected.tsv"), sep="\t", skiprows=13, low_memory=False)
key = "public_client_id"; feats = [c for c in df.columns if df[c].dtype.kind in "fi" and c != key]
X = df[feats].to_numpy(dtype=float)

# mask-and-predict CV quality (mask observed cells, impute, score) — released aggregate
rng = np.random.default_rng(0); mask = (~np.isnan(X)) & (rng.random(X.shape) < 0.1)
Xtr = X.copy(); Xtr[mask] = np.nan
imp = IterativeImputer(random_state=0, max_iter=10, sample_posterior=False).fit(Xtr)
pred = imp.transform(Xtr)
ss_res = np.nansum((X[mask] - pred[mask])**2); ss_tot = np.nansum((X[mask] - np.nanmean(X))**2)
cv_r2 = float(1 - ss_res/ss_tot) if ss_tot else float("nan")

full = IterativeImputer(random_state=0, max_iter=10).fit_transform(X)      # persist full imputed matrix
out = pd.DataFrame(full, columns=feats); out.insert(0, key, df[key].values)
out.to_csv(os.path.join(LAYER_DIR, "data.tsv.gz"), sep="\t", index=False, compression="gzip")

pd.DataFrame({"metric": ["cv_r2", "n_features", "n_rows", "pct_missing_before"],
              "value": [round(cv_r2,4), len(feats), len(df), round(float(np.isnan(X).mean()*100),2)]}
             ).to_csv(os.path.join(OUTPUT_DIR, "metabolomics_imputed__quality.csv"), index=False)
```

- [ ] **Step 2: Local smoke test against a synthetic fixture** (no real data): create a tiny `metabolomics_corrected.tsv` fixture with 13 comment lines + header + numeric columns with NaNs; set the three env vars to tmp dirs; run the script with `.venv/bin/python`; assert `LAYER_DIR/data.tsv.gz` and `OUTPUT_DIR/*quality.csv` exist and `cv_r2` is finite.
Run: `.venv/bin/pytest tests/gate/test_exemplar_impute.py -v` (write this fixture test).
Expected: PASS.

- [ ] **Step 3: Commit**
```bash
git add docs/examples/impute-metabolomics.py tests/gate/test_exemplar_impute.py
git commit -m "docs(example): metabolomics imputation derivation (fit in-sandbox, release CV-R2 only)"
```

---

## Self-Review

**Spec coverage:** §1 store→Task 7 (+0700 check); §2 two verbs/binds→Tasks 1,3,7; §3 provenance→Task 2; §4 dictionary/synthetic→Tasks 4,5; §5 disclosure+sensitivity→Tasks 3,5,6; §6 exemplar→Task 8; §7 testing→woven + Task 6. No gaps.

**Placeholder scan:** none — every code step is complete and runnable.

**Type consistency:** `run(..., derived_dir, layer_dir, layer_name, dict_path)`, `persist_layer(...)->manifest dict` (keys `name/data_hash/data_file/n_persons/fit_quality`), `read_layer_frame`, `profile_dataframe`, `add_layer_to_dictionary` are used identically across Tasks 1–8. `JOIN_KEY="public_client_id"` and the `SYNTH_%04d` pool match `build_dictionary`.

**Ordering:** 1(read bind) → 2(persist) → 3(derivation mode) → 4(profiler) → 5(auto-profile wire) → 6(adversarial) → 7(provision) → 8(exemplar). Each ends with an independently testable deliverable.

## Non-goals (v1)
Versioned `<name>@<hash>` addressing; layers beyond imputation; query-volume/differencing monitor; cleanup of unrelated dangling skill symlinks.
