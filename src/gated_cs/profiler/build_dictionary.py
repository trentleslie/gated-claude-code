import argparse, hashlib, json, os, subprocess, sys
import pandas as pd
from .profile import profile_file, profile_column
from .parse import parse_file
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
                                       text=True, stderr=subprocess.DEVNULL).splitlines()
    except Exception:
        return []

def _codebook_text(path, cap=1000):
    # Codebook files (role=="codebook") are study-instrument reference metadata
    # (field names / question text), not per-subject rows — the normal
    # k-anonymity categorical suppression (profile_column requires >=k
    # occurrences of a value) would blank out exactly the free text we want
    # to surface, since every field/question is typically unique. Re-read the
    # raw text directly for rendering instead of relying on prof["columns"].
    # Caller must gate this behind a no-subject-key check (see build()); the
    # per-column cap is defense-in-depth to bound the blast radius if a
    # misclassified file ever reaches here.
    parsed = parse_file(path)
    header_line = max(parsed.data_start_line - 1, 0)
    df = pd.read_csv(path, sep=parsed.delimiter, skiprows=header_line,
                     header=0, low_memory=False)
    out = {}
    for name in parsed.header:
        vals = sorted(str(v) for v in df[name].dropna().unique())
        if len(vals) > cap:
            extra = len(vals) - cap
            vals = vals[:cap] + [f"…({extra} more)"]
        out[name] = vals
    return out

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
        prof["source"], prof["stage"] = df_.source, df_.stage
        jk = detect_subject_key(list(prof["columns"].keys()))
        # A genuine REDCap instrument (questions/response_options) has NO subject
        # key. The codebook raw-text bypass sidesteps SDC suppression, so gate it
        # behind that structural check — a per-subject file merely *named* like a
        # codebook (has subject_id/email/free-text) is downgraded to "data" and
        # profiled+suppressed normally, never raw-dumped. See _codebook_text.
        is_codebook = df_.role == "codebook" and jk is None
        prof["role"] = "codebook" if is_codebook else "data"
        if is_codebook:
            prof["codebook_text"] = _codebook_text(df_.path)
        files[df_.relpath] = prof
        sources.setdefault(df_.source, {})[df_.relpath] = prof
        manifest_files[df_.relpath] = {"sha256": _sha256(df_.path), "bytes": size,
                                       "row_count": prof["row_count"]}
        # synthetic sample (skip codebook — it's reference metadata, not per-person rows)
        if not is_codebook:
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
            if prof.get("role") == "codebook":
                for cname, vals in prof.get("codebook_text", {}).items():
                    if vals:
                        out.append(f"\n**{cname}:** " + "; ".join(vals) + "\n")
    return "".join(out)

def profile_dataframe(df, thresholds=DEFAULTS):
    cols = {name: profile_column(df[name], name=name, thresholds=thresholds) for name in df.columns}
    return {"file_metadata": [], "row_count": int(df.shape[0]), "columns": cols}

def add_layer_to_dictionary(dict_path, out_dir, name, df, thresholds=DEFAULTS,
                            join_keys=("public_client_id",), id_pool_size=50):
    with open(dict_path) as f: d = json.load(f)
    prof = profile_dataframe(df, thresholds); prof["derived"] = True
    d["files"][name] = prof
    # _render_md iterates d["sources"]; register derived layers (no device folder)
    # under the "" root source so they aren't silently dropped from dictionary.md.
    d.setdefault("sources", {}).setdefault("", {})[name] = prof
    with open(dict_path, "w") as f: json.dump(d, f, indent=2)
    with open(os.path.join(os.path.dirname(dict_path), "dictionary.md"), "w") as f:
        f.write(_render_md(d))
    ss = os.path.join(out_dir, "synthetic_samples"); os.makedirs(ss, exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    synth = synthesize(prof, n_rows=100, seed=0, join_keys=join_keys, id_pool=id_pool)
    synth.to_csv(os.path.join(ss, name if name.endswith(".csv") else name + ".csv"), index=False)
    return prof

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--out", default=None,
                    help="Output dir; defaults to ~/claude-time-dictionary/<UTC-timestamp>/")
    a = ap.parse_args()
    build(a.data_dir, a.out)

def build_synthetic_from_dictionary(dict_path, out_dir, join_keys=None,
                                    id_pool_size=50, n_rows=100, seed=0):
    # Regenerate synthetic samples from a dictionary alone (no raw-data read). Matches build():
    # keys may be nested (source/name.csv) so parent dirs are created; the join key is auto-detected
    # per file when not supplied; codebook files carry no synthetic sample. join_keys, if given,
    # overrides detection for every file.
    with open(dict_path) as f:
        d = json.load(f)
    ss = os.path.join(out_dir, "synthetic_samples")
    os.makedirs(ss, exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    written = 0
    for name, prof in d["files"].items():
        if prof.get("role") == "codebook":
            continue
        jk = join_keys
        if jk is None:
            detected = detect_subject_key(list(prof["columns"].keys()))
            jk = (detected,) if detected else ()
        synth = synthesize(prof, n_rows=n_rows, seed=seed, join_keys=jk, id_pool=id_pool)
        dest = os.path.join(ss, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        synth.to_csv(dest, index=False)
        written += 1
    return written

def synthetic_main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dictionary", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--join-keys", default=None,
                    help="comma-separated join keys; default: auto-detect the subject key per file")
    ap.add_argument("--id-pool-size", type=int, default=50)
    a = ap.parse_args()
    join_keys = tuple(k.strip() for k in a.join_keys.split(",") if k.strip()) if a.join_keys else None
    n = build_synthetic_from_dictionary(a.dictionary, a.out, join_keys=join_keys,
                                        id_pool_size=a.id_pool_size)
    print(f"Wrote synthetic samples for {n} files to {os.path.join(a.out, 'synthetic_samples')}")

if __name__ == "__main__":
    main()
