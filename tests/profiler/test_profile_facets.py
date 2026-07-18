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
