import json
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.temporal_dist import temporal_distribution


def _longitudinal(n_subj=12, days=5, per_day=6):
    rows = []
    for s in range(n_subj):
        for d in range(days):
            for h in range(per_day):
                rows.append({"subject_id": f"S{s:03d}",
                             "timestamp": pd.Timestamp("2025-01-01")
                             + pd.Timedelta(days=d) + pd.Timedelta(hours=8 + h)})
    return pd.DataFrame(rows)


def test_happy_path_has_all_distributions():
    df = _longitudinal()
    td = temporal_distribution(df, "timestamp", "subject_id", DEFAULTS)
    assert td is not None
    for key in ("cadence", "session_minutes", "gap_hours", "diurnal_blocks",
                "coverage_days", "active_day_rate", "n_contributors"):
        assert key in td, f"missing {key}"


def test_single_event_column_yields_no_distribution():
    # one timestamp per subject -> quasi-identifier, not longitudinal (R16)
    rows = [{"subject_id": f"S{s:03d}",
             "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(days=s)}
            for s in range(20)]
    df = pd.DataFrame(rows)
    assert temporal_distribution(df, "timestamp", "subject_id", DEFAULTS) is None


def test_below_k_subjects_suppressed():
    df = _longitudinal(n_subj=3)          # < k=5 contributors
    assert temporal_distribution(df, "timestamp", "subject_id", DEFAULTS) is None


def test_diurnal_emitted_in_four_hour_blocks():
    df = _longitudinal()
    td = temporal_distribution(df, "timestamp", "subject_id", DEFAULTS)
    blocks = td["diurnal_blocks"]
    assert len(blocks) == 24 // DEFAULTS.diurnal_block_hours   # 6 coarse blocks, not 24 hours
    assert abs(sum(blocks.values()) - 1.0) < 1e-6


def test_coverage_is_enrollment_relative_no_absolute_dates():
    df = _longitudinal()
    td = temporal_distribution(df, "timestamp", "subject_id", DEFAULTS)
    blob = json.dumps(td)
    assert "2025" not in blob                 # no absolute calendar year/date leaks
    assert "2025-01" not in blob


def test_no_per_subject_array_in_facet():
    df = _longitudinal()
    td = temporal_distribution(df, "timestamp", "subject_id", DEFAULTS)
    # every value is a scalar or an aggregate bucket list — no subject-length array
    n_subj = df["subject_id"].nunique()

    def _no_subject_len(obj):
        if isinstance(obj, list):
            assert len(obj) != n_subj, "per-subject-length array leaked into facet"
            for x in obj:
                _no_subject_len(x)
        elif isinstance(obj, dict):
            for v in obj.values():
                _no_subject_len(v)

    _no_subject_len(td)


def test_bins_respect_bin_min_count():
    df = _longitudinal(n_subj=20, days=8, per_day=6)
    td = temporal_distribution(df, "timestamp", "subject_id", DEFAULTS)
    for hist_key in ("session_minutes", "gap_hours", "coverage_days"):
        for b in td[hist_key]:
            assert b["count"] >= DEFAULTS.bin_min_count


# ---- Greptile P1: a diurnal block with < k contributing subjects is suppressed ----

def test_diurnal_singleton_block_suppressed():
    rows = []
    for s in range(8):                       # 8 subjects active midday -> blocks survive
        for d in range(4):
            for h in (10, 11, 12, 13):
                rows.append({"subject_id": f"S{s:03d}",
                             "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(days=d, hours=h)})
    for d in range(4):                       # one lone subject active at 02:00 (00-04 block)
        rows.append({"subject_id": "S000",
                     "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(days=d, hours=2)})
    td = temporal_distribution(pd.DataFrame(rows), "timestamp", "subject_id", DEFAULTS)
    assert td is not None
    assert td["diurnal_blocks"]["00-04"] == 0.0            # sole-contributor block zeroed
    assert sum(td["diurnal_blocks"].values()) > 0          # midday blocks survive
