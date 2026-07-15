import pandas as pd
from .parse import parse_file
from ..config import DEFAULTS

def _histogram(s, thresholds):
    s = s.dropna()
    if s.empty:
        return []
    binned = pd.cut(s, bins=min(10, max(1, s.nunique())))
    out = []
    for interval, count in binned.value_counts().sort_index().items():
        if count >= thresholds.bin_min_count:
            out.append({"lo": float(interval.left), "hi": float(interval.right),
                        "count": int(count)})
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
