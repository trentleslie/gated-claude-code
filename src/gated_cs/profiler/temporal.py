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
    if pd.isna(min_ts) or pd.isna(max_ts):
        return {"min_month": None, "max_month": None}
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
    ts = pd.to_datetime(ts_sample, errors="coerce", format="mixed")
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
