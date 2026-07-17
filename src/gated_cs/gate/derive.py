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
