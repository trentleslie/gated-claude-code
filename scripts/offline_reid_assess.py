"""Offline pre-disclosure gate: validate the dictionary's SDC controls against the REAL
cohort and measure synthetic-vs-real temporal fidelity.

This is the check CI cannot do: CI runs on synthetic fixtures, but re-identification risk
is a property of the *real* ~37-subject data. Run ON the box; the report it writes contains
ONLY aggregate counts / divergence metrics — never a subject id, a raw timestamp, or a
per-subject value.

Usage:  PYTHONPATH=/root/gated-cs-new python offline_reid_assess.py <DATA_DIR> <DICT_OUT_DIR> <REPORT_PATH>

Two jobs (plan's required pre-disclosure gate):
  (1) Re-identification: for every DISCLOSED element (format descriptor, diurnal block,
      histogram bin), recompute from real data how many distinct subjects contribute to it.
      A disclosed element with < k real contributors is a re-id leak. Cross-column and
      cross-file: flag any real subject who is the SOLE contributor to any disclosed element.
  (2) Fidelity (directional): compare the synthetic samples' temporal shape to the real
      cohort's (cadence bucket, diurnal L1 distance, coverage/session/gap medians).
"""
import os, sys, json
import numpy as np
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.parse import parse_file
from gated_cs.profiler.discover import discover_files
from gated_cs.profiler.subject_key import detect_subject_key
from gated_cs.profiler.temporal import is_datetime_name, is_birth_name, epoch_unit

DATA_DIR, OUT_DIR, REPORT_PATH = sys.argv[1], sys.argv[2], sys.argv[3]
K = DEFAULTS.k
BLOCK_W = DEFAULTS.diurnal_block_hours
NBLOCKS = 24 // BLOCK_W
_SESSION_GAP_FACTOR = 4.0

dictionary = json.load(open(os.path.join(OUT_DIR, "dictionary.json")))


def load_df(path):
    parsed = parse_file(path)
    header_line = max(parsed.data_start_line - 1, 0)
    df = pd.read_csv(path, sep=parsed.delimiter, skiprows=header_line, header=0, low_memory=False)
    return df


def parse_ts(df, name):
    if pd.api.types.is_numeric_dtype(df[name]):
        u = epoch_unit(df[name]) if is_datetime_name(name) else None
        return pd.to_datetime(df[name], errors="coerce", unit=u, utc=True) if u else None
    if not is_datetime_name(name) and not pd.api.types.is_datetime64_any_dtype(df[name]):
        return None
    return pd.to_datetime(df[name], errors="coerce", utc=True, format="mixed")


def subject_features(g_ts):
    """Per-subject (session_minutes[], gap_hours[], coverage_days) — mirrors temporal_dist."""
    ts = pd.Series(pd.to_datetime(g_ts)).sort_values().reset_index(drop=True)
    span_days = (ts.iloc[-1] - ts.iloc[0]).total_seconds() / 86400.0 if len(ts) else 0.0
    sess, gaps = [], []
    if len(ts) >= 2:
        deltas = ts.diff().dropna().dt.total_seconds().to_numpy()
        med = float(np.median(deltas))
        gap_break = max(_SESSION_GAP_FACTOR * med, 1.0) if med > 0 else np.inf
        start = 0
        for i, d in enumerate(deltas):
            if d > gap_break:
                gaps.append(d / 3600.0)
                seg = ts.iloc[start:i + 1]
                sess.append((seg.iloc[-1] - seg.iloc[0]).total_seconds() / 60.0)
                start = i + 1
        seg = ts.iloc[start:]
        sess.append((seg.iloc[-1] - seg.iloc[0]).total_seconds() / 60.0)
    return sess, gaps, span_days


def subjects_per_bin(values_by_subject, bins):
    """For each disclosed [lo,hi) bin, count distinct subjects with a value inside it."""
    out = []
    for b in bins:
        lo, hi = b["lo"], b["hi"]
        subs = {sid for sid, vals in values_by_subject.items()
                if any(lo <= v < hi for v in vals)}
        out.append({"lo": lo, "hi": hi, "disclosed_count": b["count"], "real_subjects": len(subs)})
    return out


report = {"k": K, "diurnal_block_hours": BLOCK_W, "files": {}, "reid_leaks": [],
          "sole_contributor_subjects": 0, "fidelity": {}}
# subject -> number of disclosed elements they are the SOLE real contributor to (cross-file)
sole_hits = {}

for dfrec in discover_files(DATA_DIR):
    prof = dictionary["files"].get(dfrec.relpath)
    if not prof or prof.get("role") == "codebook":
        continue
    subject_key = detect_subject_key(list(prof["columns"].keys()))
    if subject_key is None:
        continue
    df = load_df(dfrec.path)
    frec = {"columns": {}}
    for name, col in prof["columns"].items():
        has_fmt, has_td = "format" in col, "temporal_distribution" in col
        if not (has_fmt or has_td):
            continue
        ts = parse_ts(df, name)
        if ts is None:
            continue
        fr = pd.DataFrame({"sid": df[subject_key].values, "ts": ts.values}).dropna(subset=["ts"])
        if fr.empty:
            continue
        col_report = {"real_contributors": int(fr["sid"].nunique())}

        # (1a) format descriptor is disclosed only when the whole column has >= k real subjects
        if has_fmt:
            ok = col_report["real_contributors"] >= K
            col_report["format_disclosed_ge_k"] = ok
            if not ok:
                report["reid_leaks"].append(
                    {"file": dfrec.relpath, "column": name, "element": "format_descriptor",
                     "real_contributors": col_report["real_contributors"]})

        if has_td:
            td = col["temporal_distribution"]
            hh = pd.to_datetime(fr["ts"]).dt.hour
            fr = fr.assign(blk=(hh // BLOCK_W).astype(int))
            blk_subj = fr.groupby("blk")["sid"].nunique().to_dict()
            # (1b) every NONZERO disclosed diurnal block must have >= k real contributors
            diurnal = []
            for b in range(NBLOCKS):
                label = f"{b * BLOCK_W:02d}-{(b + 1) * BLOCK_W:02d}"
                disclosed = float(td.get("diurnal_blocks", {}).get(label, 0.0))
                real_subj = int(blk_subj.get(b, 0))
                diurnal.append({"block": label, "disclosed_weight": disclosed, "real_subjects": real_subj})
                if disclosed > 0 and real_subj < K:
                    report["reid_leaks"].append(
                        {"file": dfrec.relpath, "column": name, "element": f"diurnal:{label}",
                         "real_subjects": real_subj})
                if disclosed > 0 and real_subj == 1:
                    lone = fr[fr["blk"] == b]["sid"].iloc[0]
                    sole_hits[lone] = sole_hits.get(lone, 0) + 1
            col_report["diurnal"] = diurnal

            # (1c) histogram bins: count distinct real subjects per disclosed bin
            sess_by, gap_by, cov_by = {}, {}, {}
            for sid, g in fr.groupby("sid", sort=False):
                s, gp, cov = subject_features(g["ts"])
                sess_by[sid], gap_by[sid], cov_by[sid] = s, gp, [cov]
            for key, vals_by in (("session_minutes", sess_by), ("gap_hours", gap_by),
                                 ("coverage_days", cov_by)):
                bins = td.get(key) or []
                per_bin = subjects_per_bin(vals_by, bins)
                col_report[key] = per_bin
                for pb in per_bin:
                    if pb["real_subjects"] < K:
                        report["reid_leaks"].append(
                            {"file": dfrec.relpath, "column": name,
                             "element": f"{key}[{pb['lo']},{pb['hi']})",
                             "real_subjects": pb["real_subjects"]})
                    if pb["real_subjects"] == 1:
                        for sid, vals in vals_by.items():
                            if any(pb["lo"] <= v < pb["hi"] for v in vals):
                                sole_hits[sid] = sole_hits.get(sid, 0) + 1
                                break

            # (2) fidelity: synthetic vs real, this column
            syn_path = os.path.join(OUT_DIR, "synthetic_samples", dfrec.relpath)
            if os.path.exists(syn_path):
                syn = pd.read_csv(syn_path)
                if name in syn.columns:
                    sts = pd.to_datetime(syn[name], errors="coerce", utc=True, format="mixed")
                    if pd.api.types.is_numeric_dtype(syn[name]):  # epoch synthetic
                        u = epoch_unit(syn[name])
                        if u:
                            sts = pd.to_datetime(syn[name], errors="coerce", unit=u, utc=True)
                    sts = sts.dropna()
                    if sts.dt.tz is not None:
                        sts = sts.dt.tz_localize(None)          # naive UTC, matches real below
                    if len(sts):
                        real = pd.to_datetime(fr["ts"])          # naive (numpy datetime64 values)
                        real_min, real_max = real.min(), real.max()
                        real_h = np.bincount((hh // BLOCK_W).astype(int), minlength=NBLOCKS).astype(float)
                        real_h = real_h / real_h.sum() if real_h.sum() else real_h
                        syn_hh = (sts.dt.hour // BLOCK_W).astype(int)
                        syn_h = np.bincount(syn_hh, minlength=NBLOCKS).astype(float)
                        syn_h = syn_h / syn_h.sum() if syn_h.sum() else syn_h
                        col_report["fidelity"] = {
                            "diurnal_L1": round(float(np.abs(real_h - syn_h).sum()), 4),
                            "real_min_month": real_min.strftime("%Y-%m"),
                            "syn_min_month": sts.min().strftime("%Y-%m"),
                            "syn_in_real_range": bool(real_min.floor("D") <= sts.min()
                                                      and sts.max() <= real_max.ceil("D")),
                        }
        frec["columns"][name] = col_report
    if frec["columns"]:
        report["files"][dfrec.relpath] = frec

report["sole_contributor_subjects"] = len(sole_hits)   # cross-file uniqueness fingerprints
report["reid_pass"] = (len(report["reid_leaks"]) == 0 and len(sole_hits) == 0)

os.makedirs(os.path.dirname(REPORT_PATH) or ".", exist_ok=True)
with open(REPORT_PATH, "w") as f:
    json.dump(report, f, indent=2, default=str)

print(f"[assess] reid_pass={report['reid_pass']}  "
      f"leaks={len(report['reid_leaks'])}  sole_contributor_subjects={len(sole_hits)}")
print(f"[assess] report written to {REPORT_PATH}")
