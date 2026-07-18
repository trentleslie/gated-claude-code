import math
import numpy as np
import pandas as pd
from .parse import parse_file
from .subject_key import detect_subject_key, cohort_n
from .temporal import is_datetime_name, month_bounds, cadence_label
from ..config import DEFAULTS

def _nice_step(span, target_bins=10):
    # data-independent "nice" step (1/2/2.5/5 x 10^k) so bin edges are round
    # grid multiples, never exact sample values.
    if not math.isfinite(span) or span <= 0:
        return 1.0
    raw = span / target_bins
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag

def _nice_edges(lo_v, hi_v, thresholds):
    step = _nice_step(hi_v - lo_v)
    start = math.floor(lo_v / step) * step
    end = (math.floor(hi_v / step) + 1) * step   # strictly > hi_v so max is never an edge
    edges, e = [], start
    while e <= end + step / 2:
        edges.append(round(e, 10))
        e += step
    return edges

def _histogram(s, thresholds):
    s = s.dropna()
    s = s[np.isfinite(s)]          # drop inf/-inf — cannot be binned, and break edge math
    if s.empty:
        return []
    if s.nunique() < 2:
        return []  # constant column: any bin would pin the shared value; nothing safe to bin
    lo_v, hi_v = float(s.min()), float(s.max())
    edges = _nice_edges(lo_v, hi_v, thresholds)
    counts = pd.cut(s, bins=edges, include_lowest=True, right=False).value_counts().sort_index()
    out = []
    for interval, count in counts.items():
        if int(count) >= thresholds.bin_min_count:
            out.append({"lo": float(interval.left), "hi": float(interval.right), "count": int(count)})
    return out

def profile_column(series, name="", thresholds=DEFAULTS):
    from .sensitivity import is_sensitive
    n = int(series.shape[0])
    out = {"dtype": str(series.dtype), "n": n,
           "pct_missing": round(float(series.isna().mean()) * 100, 2),
           "cardinality": int(series.nunique(dropna=True)),
           "sensitive": is_sensitive(name, series, thresholds)}
    if out["sensitive"]:
        out["values_suppressed"] = True
        out["categories"] = None
        return out
    if pd.api.types.is_numeric_dtype(series):
        out["histogram"] = _histogram(series, thresholds)
    else:
        if out["cardinality"] <= thresholds.cardinality_cap:
            counts = series.dropna().astype(str).value_counts()
            out["categories"] = sorted(str(v) for v, c in counts.items() if c >= thresholds.k)
            n_rare = int((counts < thresholds.k).sum())
            if n_rare:
                out["rare_categories_suppressed"] = n_rare
        else:
            out["categories"] = None
            out["suppressed_high_cardinality"] = True
    return out

def _attach_facets(df, parsed, cols, thresholds, sample_rows):
    subject_key = detect_subject_key(parsed.header)
    cn = int(cohort_n(df[subject_key])) if subject_key else None
    sid_sample = df[subject_key].head(sample_rows) if subject_key else None
    for name in parsed.header:
        if not is_datetime_name(name) and not pd.api.types.is_datetime64_any_dtype(df[name]):
            continue
        ts = pd.to_datetime(df[name], errors="coerce").dropna()
        if ts.empty:
            continue
        cov = month_bounds(ts.min(), ts.max())
        cov["n_timestamps"] = int(ts.shape[0])
        cov["cadence"] = cadence_label(df[name].head(sample_rows), sid_sample)
        cols[name]["temporal_coverage"] = cov
    return subject_key, cn

def profile_file(path, thresholds=DEFAULTS, sample_rows=None):
    parsed = parse_file(path)
    header_line = max(parsed.data_start_line - 1, 0)
    df = pd.read_csv(path, sep=parsed.delimiter, skiprows=header_line,
                     header=0, low_memory=False)
    cols = {}
    for name in parsed.header:
        col = profile_column(df[name], name=name, thresholds=thresholds)
        if name in parsed.column_descriptions:
            col["description"] = parsed.column_descriptions[name]
        cols[name] = col
    sample_rows = sample_rows or thresholds.cadence_sample_rows
    subject_key, cn = _attach_facets(df, parsed, cols, thresholds, sample_rows)
    return {"path": path, "delimiter": parsed.delimiter, "row_count": int(df.shape[0]),
            "file_metadata": parsed.file_metadata, "columns": cols,
            "subject_key": subject_key, "cohort_n": cn}
