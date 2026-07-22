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

def test_cadence_label_global_fallback_no_sids():
    base = pd.Timestamp("2025-01-01")
    ts = pd.Series([base + pd.Timedelta(minutes=5 * i) for i in range(10)])
    assert cadence_label(ts) == "~1/5 min"

def test_is_datetime_name():
    assert is_datetime_name("timestamp") and is_datetime_name("created_at")
    assert is_datetime_name("bedtime_start") and not is_datetime_name("heart_rate")

def test_cadence_label_mixed_utc_offsets_no_warning():
    # real wearable data mixes offsets (e.g. device-local vs UTC) within one column;
    # each pair below is 5 minutes apart once normalized to UTC.
    ts = pd.Series(["2025-01-01T00:00:00+00:00", "2024-12-31T16:05:00-08:00",
                     "2025-01-01T00:00:00-08:00", "2025-01-01T08:05:00+00:00"])
    sid = pd.Series(["A", "A", "B", "B"])
    assert cadence_label(ts, sid) == "~1/5 min"
