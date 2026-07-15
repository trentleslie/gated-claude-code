import math
import pandas as pd
from .parse import parse_file
from ..config import DEFAULTS

def _nice_step(span, target_bins=10):
    # data-independent "nice" step (1/2/2.5/5 x 10^k) so bin edges are round
    # grid multiples, never exact sample values.
    if span <= 0:
        return 1.0
    raw = span / target_bins
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag

def _histogram(s, thresholds):
    s = s.dropna()
    if s.empty:
        return []
    if s.nunique() < 2:
        return []  # constant column: any bin would pin the shared value; nothing safe to bin
    lo_v, hi_v = float(s.min()), float(s.max())
    step = _nice_step(hi_v - lo_v)
    start = math.floor(lo_v / step) * step
    end = (math.floor(hi_v / step) + 1) * step   # strictly > hi_v so max is never an edge
    edges = []
    e = start
    while e <= end + step / 2:
        edges.append(round(e, 10))
        e += step
    counts = pd.cut(s, bins=edges, include_lowest=True, right=False).value_counts().sort_index()
    out = []
    for interval, count in counts.items():
        if int(count) >= thresholds.bin_min_count:
            out.append({"lo": float(interval.left), "hi": float(interval.right), "count": int(count)})
    return out

def profile_column(series, thresholds=DEFAULTS):
    n = int(series.shape[0])
    out = {"dtype": str(series.dtype), "n": n,
           "pct_missing": round(float(series.isna().mean()) * 100, 2),
           "cardinality": int(series.nunique(dropna=True))}
    if pd.api.types.is_numeric_dtype(series):
        out["histogram"] = _histogram(series, thresholds)
    else:
        if out["cardinality"] <= thresholds.cardinality_cap:
            out["categories"] = sorted(series.dropna().astype(str).unique().tolist())
        else:
            out["categories"] = None
            out["suppressed_high_cardinality"] = True
    return out

def profile_file(path, thresholds=DEFAULTS):
    parsed = parse_file(path)
    df = pd.read_csv(path, sep=parsed.delimiter, comment="#")
    cols = {}
    for name in parsed.header:
        col = profile_column(df[name], thresholds)
        if name in parsed.column_descriptions:
            col["description"] = parsed.column_descriptions[name]
        cols[name] = col
    return {"path": path, "delimiter": parsed.delimiter, "row_count": int(df.shape[0]),
            "file_metadata": parsed.file_metadata, "columns": cols}
