import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.profile import profile_file

def _write(tmp_path):
    rows = []
    for sid in range(20):
        for i in range(48):  # every 30 min across ~1 day
            rows.append({"subject_id": f"S{sid:03d}",
                         "timestamp": pd.Timestamp("2025-03-01") + pd.Timedelta(minutes=30 * i),
                         "hr": 50 + (i % 40)})
    p = tmp_path / "hr.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)

def test_profile_file_emits_subject_key_cohort_and_temporal(tmp_path):
    prof = profile_file(_write(tmp_path), DEFAULTS)
    assert prof["subject_key"] == "subject_id"
    assert prof["cohort_n"] == 20
    ts = prof["columns"]["timestamp"]
    assert ts["sensitive"] is True                      # still suppressed
    assert "categories" not in ts or ts.get("values_suppressed")
    cov = ts["temporal_coverage"]
    assert cov["min_month"] == "2025-03" and cov["max_month"] == "2025-03"
    assert cov["cadence"] in ("~1/15 min", "~1/hour")   # 30-min spacing bucket boundary
    assert cov["n_timestamps"] == 20 * 48
    # subject_id column present and suppressed as identifier
    assert prof["columns"]["subject_id"]["sensitive"] is True

def _write_mixed_tz(tmp_path):
    # real wearable timestamps carry mixed UTC offsets across rows/subjects
    stamps = ["2025-01-01T00:00:00+00:00", "2025-01-01T02:00:00-08:00",
              "2025-06-15T12:00:00+00:00", "2025-06-15T10:00:00-08:00"]
    rows = []
    for sid in range(3):
        for i, ts in enumerate(stamps):
            rows.append({"subject_id": f"S{sid:03d}", "timestamp": ts,
                         "resting_time": 1800 + i})  # int64 duration in seconds, name looks like a datetime
    p = tmp_path / "mixed_tz.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return str(p)

def test_profile_file_mixed_tz_timestamps_no_warning(tmp_path, recwarn):
    prof = profile_file(_write_mixed_tz(tmp_path), DEFAULTS)
    cov = prof["columns"]["timestamp"]["temporal_coverage"]
    # min/max computed in UTC: Jan 1 and Jun 15, regardless of local offset
    assert cov["min_month"] == "2025-01" and cov["max_month"] == "2025-06"
    assert cov["cadence"] is not None and cov["cadence"] != "unknown"
    assert len(recwarn) == 0

def test_profile_file_numeric_duration_column_skips_temporal_coverage(tmp_path):
    prof = profile_file(_write_mixed_tz(tmp_path), DEFAULTS)
    resting = prof["columns"]["resting_time"]
    assert "temporal_coverage" not in resting  # int seconds, not a real datetime
    assert resting["dtype"].startswith("int")  # still profiled normally


def test_numeric_epoch_timestamp_is_profiled(tmp_path):
    # Greptile P1: an epoch-seconds int column named 'timestamp' must be detected as a
    # timestamp (format + temporal capture), not skipped as a generic numeric column.
    base = int(pd.Timestamp("2025-03-01").timestamp())
    rows = [{"subject_id": f"S{sid:03d}", "timestamp": base + i * 3600, "hr": 60}
            for sid in range(10) for i in range(30)]          # hourly epoch seconds
    p = tmp_path / "epoch.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    ts = profile_file(str(p), DEFAULTS)["columns"]["timestamp"]
    assert ts.get("format", {}).get("representation") == "epoch_s"
    assert "temporal_distribution" in ts                      # epoch col gets temporal capture
    assert ts["temporal_coverage"]["min_month"] == "2025-03"
