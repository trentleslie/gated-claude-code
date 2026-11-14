import argparse, hashlib, json, os, subprocess, sys
import pandas as pd
from .profile import profile_file, profile_column
from .parse import read_table, is_parquet
from .synthesize import synthesize
from .discover import discover_files
from .subject_key import detect_subject_key
from .sensitivity import UUID_TOKEN, as_text, contains_uuid, uuid_mask
from ..config import DEFAULTS

class PublishedUUIDError(RuntimeError):
    """A UUID-shaped value reached (or would reach) a published artifact."""

def _redact(text):
    return UUID_TOKEN.sub("<uuid>", str(text))

def _dictionary_findings(node, path="dictionary.json"):
    # every string a dictionary publishes, keys included: category values are filtered in
    # profile_column, but comment lines, descriptions, column names and file paths are
    # copied from the source verbatim. Locations are redacted so the error names the field
    # without repeating the value.
    out = []
    if isinstance(node, dict):
        for k, v in node.items():
            here = f"{path}[{_redact(k)!r}]"
            if contains_uuid(k):
                out.append(here + " (name)")
            out += _dictionary_findings(v, here)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _dictionary_findings(v, f"{path}[{i}]")
    elif isinstance(node, str) and contains_uuid(node):
        out.append(path)
    return out

def _text_findings(text, label):
    return [f"{label} line {i}" for i, line in enumerate(text.splitlines(), 1)
            if UUID_TOKEN.search(line)]

def _frame_findings(df, label):
    return [f"{label} column {i}" for i, c in enumerate(df.columns)
            if contains_uuid(c) or uuid_mask(df[c]).any()]

def _sample_findings(path, label):
    try:
        if is_parquet(path):
            return _frame_findings(pd.read_parquet(path), label)
        with open(path, "rb") as f:
            return _text_findings(f.read().decode("utf-8", "ignore"), label)
    except Exception:
        return [f"{label} (unreadable, cannot be checked)"]

def _scan_samples(out_dir):
    # {path: findings} for every file under synthetic_samples, stale ones included
    ss, found = os.path.join(out_dir, "synthetic_samples"), {}
    def _unreadable(err):
        # os.walk skips a directory it cannot list unless told otherwise; an unchecked
        # subtree must fail the build, exactly as an unreadable file does
        where = err.filename or ss
        found[where] = [f"{_redact(os.path.relpath(where, out_dir))} (unreadable directory, cannot be checked)"]
    for root, dirs, names in os.walk(ss, onerror=_unreadable):
        for dn in dirs:
            # os.walk lists a symlinked directory but never descends into it
            full = os.path.join(root, dn)
            if os.path.islink(full):
                found[full] = [f"{_redact(os.path.relpath(full, out_dir))} (symlinked directory, cannot be checked)"]
        for fn in names:
            full = os.path.join(root, fn)
            hits = _sample_findings(full, _redact(os.path.relpath(full, out_dir)))
            if hits:
                found[full] = hits
    return found

def _fail_closed(findings, remove):
    # Fail-closed pre-release check: nothing this run wrote stays readable, and the message
    # names each file and field (never the value) so the operator can fix the source.
    for p in remove:
        try:
            os.remove(p)
        except OSError:
            pass
    shown = "; ".join(findings[:20]) + (f"; ...and {len(findings) - 20} more" if len(findings) > 20 else "")
    what = ("UUID-shaped value found in published output; this run's artifacts were removed. "
            if remove else
            "UUID-shaped value would reach published output; nothing was written. ")
    raise PublishedUUIDError(f"{what}Fix or exclude the source, then rebuild. Found in: {shown}")

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
    parsed, df = read_table(path)
    out = {}
    for name in parsed.header:
        every = sorted(as_text(df[name].dropna()).unique())
        # this path bypasses profile_column, so it applies the same per-value UUID filter
        vals = [v for v in every if not contains_uuid(v)]
        n_uuid = len(every) - len(vals)
        if len(vals) > cap:
            extra = len(vals) - cap
            vals = vals[:cap] + [f"…({extra} more)"]
        if n_uuid:
            vals.append(f"…({n_uuid} UUID-shaped withheld)")
        out[name] = vals
    return out

def _restore_dtype(s, dtype):
    # Synthetic values are drawn as python floats/ints/strings; cast back to the
    # profiled dtype so a parquet sample carries the same schema as the real file
    # (datetime64, bool, category, int). Best-effort: a column that won't cast
    # stays as generated, it is fabricated either way.
    try:
        if dtype.startswith("datetime64"):
            out = pd.to_datetime(s, errors="coerce", utc=True, format="mixed")
            if "," not in dtype:
                return out.dt.tz_localize(None)
            return out.dt.tz_convert(dtype.split(",", 1)[1].rstrip("]").strip())
        if dtype in ("bool", "boolean"):
            labels = s.map(lambda v: {"true": 1, "false": 0}.get(v.lower(), v) if isinstance(v, str) else v)
            num = pd.to_numeric(labels, errors="coerce").round()
            return num.astype("boolean" if num.isna().any() else "bool")
        if dtype == "category":
            return s.astype("category")
        if dtype.lower().startswith(("int", "uint", "float")):
            num = pd.to_numeric(s, errors="coerce")
            if num.isna().any() and dtype.startswith(("int", "uint")):
                return num.round().astype(dtype.capitalize().replace("Uint", "UInt"))
            return num.astype(dtype)
    except (TypeError, ValueError, KeyError):  # KeyError: unknown tz (ZoneInfoNotFoundError)
        pass
    return s

def _write_synthetic(synth, dest, prof):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if is_parquet(dest):
        for name, col in prof["columns"].items():
            if name in synth.columns:
                synth[name] = _restore_dtype(synth[name], str(col.get("dtype", "")))
        synth.to_parquet(dest, index=False)
    else:
        synth.to_csv(dest, index=False)

def build(data_dir, out_dir=None, thresholds=DEFAULTS, id_pool_size=50):
    if out_dir is None:
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = os.path.join(os.path.expanduser("~"), "claude-time-dictionary", stamp)
    os.makedirs(os.path.join(out_dir, "synthetic_samples"), exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]

    files, sources, manifest_files, written = {}, {}, {}, []
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
            _write_synthetic(synth, dest, prof)
            written.append(dest)

    dictionary = {"data_dir": data_dir, "sources": sources, "files": files}
    dict_path, md_path = os.path.join(out_dir, "dictionary.json"), os.path.join(out_dir, "dictionary.md")
    with open(dict_path, "w") as f:
        json.dump(dictionary, f, indent=2, default=str)
    with open(md_path, "w") as f:
        f.write(_render_md(dictionary))
    # Fail-closed scan of what was just published (read back from disk). The run manifest is
    # not scanned: it holds input hashes and package versions, not data values.
    with open(dict_path) as f:
        on_disk = json.load(f)
    # ("sources" repeats "files" grouped by top-level folder, so it is walked once)
    findings = _dictionary_findings({k: v for k, v in on_disk.items() if k != "sources"})
    with open(md_path) as f:
        findings += _text_findings(f.read(), "dictionary.md")
    bad_samples = _scan_samples(out_dir)
    findings += [h for hits in bad_samples.values() for h in hits]
    if findings:
        _fail_closed(findings, [dict_path, md_path, *written, *bad_samples])
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
                fmt = c.get("format")
                if fmt:
                    # value-free template (+ mixed-format flag) only
                    ftxt = f"fmt=`{fmt['template']}`" + (" (mixed)" if fmt.get("mixed") else "")
                    note = f"{note}; {ftxt}" if note else ftxt
                td = c.get("temporal_distribution")
                if td:
                    # aggregate-only summary: coarse diurnal peak + coverage rate, no raw values
                    peak = max(td["diurnal_blocks"], key=td["diurnal_blocks"].get) \
                        if td.get("diurnal_blocks") else "?"
                    dtxt = f"struct: peak {peak}h, active {td['active_day_rate']:.0%}"
                    note = f"{note}; {dtxt}" if note else dtxt
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
    md = _render_md(d)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    synth = synthesize(prof, n_rows=100, seed=0, join_keys=join_keys, id_pool=id_pool)
    sample = name if name.endswith(".csv") else name + ".csv"
    # Same fail-closed checks as build(), run BEFORE anything is written: a derived layer's
    # name and column names (e.g. a pivot keyed on staff UUIDs) are copied verbatim into
    # both dictionary files and the sample header, so nothing is published on a finding.
    # The JSON is serialized first too, so a value json cannot encode raises here rather
    # than after dictionary.json has been truncated.
    text = json.dumps(d, indent=2)
    findings = _dictionary_findings({k: v for k, v in json.loads(text).items() if k != "sources"})
    findings += _text_findings(md, "dictionary.md")
    findings += _frame_findings(synth, _redact(os.path.join("synthetic_samples", sample)))
    if findings:
        _fail_closed(findings, [])
    with open(dict_path, "w") as f: f.write(text)
    with open(os.path.join(os.path.dirname(dict_path), "dictionary.md"), "w") as f:
        f.write(md)
    ss = os.path.join(out_dir, "synthetic_samples"); os.makedirs(ss, exist_ok=True)
    synth.to_csv(os.path.join(ss, sample), index=False)
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
    # An older dictionary (built before the per-value filter) may hold UUID-shaped
    # categories; refuse before writing anything rather than republish them.
    findings = _dictionary_findings({k: v for k, v in d.items() if k != "sources"})
    if findings:
        _fail_closed(findings, [])
    ss = os.path.join(out_dir, "synthetic_samples")
    os.makedirs(ss, exist_ok=True)
    id_pool = [f"SYNTH_{i:04d}" for i in range(id_pool_size)]
    written, paths = 0, []
    for name, prof in d["files"].items():
        if prof.get("role") == "codebook":
            continue
        jk = join_keys
        if jk is None:
            detected = detect_subject_key(list(prof["columns"].keys()))
            jk = (detected,) if detected else ()
        synth = synthesize(prof, n_rows=n_rows, seed=seed, join_keys=jk, id_pool=id_pool)
        _write_synthetic(synth, os.path.join(ss, name), prof)
        paths.append(os.path.join(ss, name))
        written += 1
    bad_samples = _scan_samples(out_dir)
    if bad_samples:
        _fail_closed([h for hits in bad_samples.values() for h in hits], [*paths, *bad_samples])
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
