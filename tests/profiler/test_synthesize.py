import pathlib
import pandas as pd
from gated_cs.profiler.profile import profile_file
from gated_cs.profiler.synthesize import synthesize

FX = pathlib.Path(__file__).parent.parent / "fixtures"

POOL = [f"SYNTH_{i:04d}" for i in range(50)]


def _longitudinal_profile(tmp_path, fmt="%Y-%m-%dT%H:%M:%SZ"):
    rows = [{"subject_id": f"S{s:03d}",
             "timestamp": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
                           + pd.Timedelta(hours=8 + h)).strftime(fmt),
             "hr": 60 + (h % 20)}
            for s in range(12) for d in range(5) for h in range(6)]
    p = tmp_path / "hr.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return profile_file(str(p))


# ---------- Unit 4: joint per-subject generation ----------

def test_rows_grouped_by_subject_and_time_ordered(tmp_path):
    prof = _longitudinal_profile(tmp_path)
    df = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    assert len(df) > 0
    for sid, g in df.groupby("subject_id"):
        ts = pd.to_datetime(g["timestamp"], format="mixed", utc=True)
        assert list(ts) == sorted(ts), f"subject {sid} timestamps not ordered"


def test_joint_output_is_deterministic(tmp_path):
    prof = _longitudinal_profile(tmp_path)
    a = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    b = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    assert a.equals(b)


def test_joint_subjects_are_heterogeneous(tmp_path):
    prof = _longitudinal_profile(tmp_path)
    df = synthesize(prof, n_rows=300, seed=0, join_keys=("subject_id",), id_pool=POOL)
    spans = df.groupby("subject_id")["timestamp"].apply(
        lambda s: pd.to_datetime(s, format="mixed", utc=True).max()
        - pd.to_datetime(s, format="mixed", utc=True).min())
    assert spans.nunique() > 1                 # not every subject identical


def test_joint_join_key_only_from_synth_pool(tmp_path):
    prof = _longitudinal_profile(tmp_path)
    df = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    assert set(df["subject_id"]) <= set(POOL)
    assert not any(str(v).startswith("S0") for v in df["subject_id"])


def test_facetless_profile_falls_back_to_iid(tmp_path):
    # a profile with a subject key but NO temporal_distribution -> legacy i.i.d. path
    prof = {"columns": {"public_client_id": {"sensitive": True, "categories": None},
                        "glucose": {"dtype": "int64", "histogram":
                                    [{"lo": 80, "hi": 100, "count": 50}]}}}
    df = synthesize(prof, n_rows=40, seed=1, join_keys=("public_client_id",), id_pool=POOL)
    assert len(df) == 40                       # legacy path keeps exact n_rows
    assert set(df["public_client_id"]) <= set(POOL)


# ---------- Unit 5: timestamp rendering from descriptor ----------

def test_iso_utc_format_rendered(tmp_path):
    prof = _longitudinal_profile(tmp_path, fmt="%Y-%m-%dT%H:%M:%SZ")
    df = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    assert df["timestamp"].astype(str).str.contains("T").all()
    assert df["timestamp"].astype(str).str.endswith("Z").all()


def test_date_only_format_has_no_time(tmp_path):
    prof = _longitudinal_profile(tmp_path, fmt="%Y-%m-%d")
    df = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    assert not df["timestamp"].astype(str).str.contains("T").any()
    assert not df["timestamp"].astype(str).str.contains(":").any()


def test_epoch_seconds_format_rendered_numeric(tmp_path):
    rows = [{"subject_id": f"S{s:03d}",
             "timestamp": int((pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
                               + pd.Timedelta(hours=8 + h)).timestamp()),
             "hr": 60 + (h % 20)}
            for s in range(12) for d in range(5) for h in range(6)]
    p = tmp_path / "epoch.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    prof = profile_file(str(p))
    df = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    assert df["timestamp"].astype(str).str.fullmatch(r"\d+").all()


def test_timestamps_within_captured_month_range(tmp_path):
    prof = _longitudinal_profile(tmp_path)
    df = synthesize(prof, n_rows=300, seed=0, join_keys=("subject_id",), id_pool=POOL)
    ts = pd.to_datetime(df["timestamp"], format="mixed", utc=True)
    assert ts.min() >= pd.Timestamp("2025-01-01", tz="UTC")
    assert ts.max() < pd.Timestamp("2025-02-01", tz="UTC")


def test_retained_minority_format_emitted_and_subk_never(tmp_path):
    # dominant ISO-Z for 12 subjects; a retained space-format minority in >= k subjects;
    # a < k minority that must never appear in synthetic output.
    rows = []
    for s in range(12):
        for d in range(5):
            for h in range(6):
                dt = pd.Timestamp("2025-01-01") + pd.Timedelta(days=d, hours=8 + h)
                rows.append({"subject_id": f"S{s:03d}",
                             "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "hr": 60})
    for s in range(6):                     # 6 subjects -> retained minority (space format)
        for d in range(5):
            dt = pd.Timestamp("2025-01-10") + pd.Timedelta(days=d, hours=10)
            rows.append({"subject_id": f"M{s:03d}",
                         "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"), "hr": 60})
    for s in range(2):                     # 2 subjects -> < k minority (must be suppressed)
        dt = pd.Timestamp("2025-01-20T10:00:00.123456")
        rows.append({"subject_id": f"R{s:03d}",
                     "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%S.%f"), "hr": 60})
    p = tmp_path / "mixed.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    prof = profile_file(str(p))
    df = synthesize(prof, n_rows=600, seed=0, join_keys=("subject_id",), id_pool=POOL)
    s_ts = df["timestamp"].astype(str)
    assert s_ts.str.endswith("Z").any()                 # dominant emitted
    assert s_ts.str.match(r"\d{4}-\d{2}-\d{2} \d").any()  # retained minority emitted
    assert not s_ts.str.contains(r"\.\d{6}").any()      # < k subsecond minority never appears


def test_ksuppressed_column_renders_format_correct_no_date_only_regression(tmp_path):
    # column with a format facet but distribution suppressed (< k subjects) still
    # renders format-correct timestamps, never the old date-only random path.
    rows = [{"subject_id": f"S{s:03d}",
             "timestamp": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=d, hours=8 + h)
                           ).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "hr": 60}
            for s in range(3) for d in range(5) for h in range(6)]  # 3 subjects < k
    p = tmp_path / "few.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    prof = profile_file(str(p))
    assert "temporal_distribution" not in prof["columns"]["timestamp"]  # suppressed
    df = synthesize(prof, n_rows=60, seed=0, join_keys=("subject_id",), id_pool=POOL)
    ts = df["timestamp"].astype(str)
    assert ts.str.endswith("Z").all()                   # format-correct, not date-only


# ---------- Unit 6: value co-location ----------

def test_value_colocation_groupby_hour_nonempty(tmp_path):
    prof = _longitudinal_profile(tmp_path)
    df = synthesize(prof, n_rows=300, seed=0, join_keys=("subject_id",), id_pool=POOL)
    df["hour"] = pd.to_datetime(df["timestamp"], format="mixed", utc=True).dt.hour
    agg = df.groupby(["subject_id", "hour"])["hr"].mean()
    assert len(agg) > 0
    # hr stays within its histogram bins
    hist = prof["columns"]["hr"]["histogram"]
    lo = min(b["lo"] for b in hist); hi = max(b["hi"] for b in hist)
    assert df["hr"].astype(float).between(lo, hi).all()


# ---------- Unit 7: sample sizing ----------

def test_each_subject_has_enough_rows_for_session_and_gap(tmp_path):
    prof = _longitudinal_profile(tmp_path)
    df = synthesize(prof, n_rows=200, seed=0, join_keys=("subject_id",), id_pool=POOL)
    counts = df.groupby("subject_id").size()
    assert (counts >= 10).all()                # enough per subject to show structure
    # at least one subject spans multiple distinct days (a gap is possible)
    days = df.assign(day=pd.to_datetime(df["timestamp"], format="mixed", utc=True).dt.date)
    per = days.groupby("subject_id")["day"].nunique()
    assert (per >= 2).any()


def test_synthetic_shape_and_columns():
    prof = profile_file(str(FX / "simple.csv"))
    df = synthesize(prof, n_rows=50, seed=1)
    assert list(df.columns) == ["age", "sex"]
    assert len(df) == 50
    assert set(df["sex"].unique()) <= {"M", "F"}


def test_sensitive_column_is_fabricated():
    prof = profile_file(str(FX / "with_ids.csv"))
    df = synthesize(prof, n_rows=10)
    assert "<suppressed>" not in df["email"].tolist()
    assert all(str(v).startswith("FAKE_") for v in df["email"])


def test_numeric_values_within_histogram_range():
    prof = profile_file(str(FX / "simple.csv"))            # age = integer column
    df = synthesize(prof, n_rows=200, seed=3)
    hist = prof["columns"]["age"]["histogram"]
    lo = min(b["lo"] for b in hist); hi = max(b["hi"] for b in hist)
    assert df["age"].astype(float).between(lo, hi).all()


def test_fractional_bin_column_not_collapsed_to_integers():
    import pandas as pd
    from gated_cs.profiler.profile import profile_column
    s = pd.Series([round(i / 100, 2) for i in range(100)])  # 0.00..0.99 -> sub-1 bins
    col = profile_column(s)
    fp = {"columns": {"p": col}}
    vals = synthesize(fp, n_rows=200, seed=1)["p"].astype(float)
    lo = min(b["lo"] for b in col["histogram"]); hi = max(b["hi"] for b in col["histogram"])
    assert vals.between(lo, hi).all()
    assert (vals % 1 != 0).any()          # not collapsed to integers


def test_deterministic_same_seed():
    prof = profile_file(str(FX / "simple.csv"))
    assert synthesize(prof, n_rows=50, seed=7).equals(synthesize(prof, n_rows=50, seed=7))


def test_empty_histogram_numeric_gets_fake_numbers():
    fp = {"columns": {"c": {"dtype": "int64", "n": 50, "pct_missing": 0.0,
                            "cardinality": 1, "sensitive": False, "histogram": []}}}
    df = synthesize(fp, n_rows=10)
    assert "<suppressed>" not in df["c"].astype(str).tolist()
    import pandas as pd
    assert pd.api.types.is_numeric_dtype(df["c"])


def test_join_key_column_uses_fake_pool_not_suppressed():
    col = {"dtype": "object", "n": 100, "pct_missing": 0.0, "cardinality": 100,
           "sensitive": True, "values_suppressed": True, "categories": None}
    fp = {"columns": {"public_client_id": col}}
    pool = [f"SYNTH_{i:04d}" for i in range(5)]
    df = synthesize(fp, n_rows=50, seed=1, join_keys={"public_client_id"}, id_pool=pool)
    assert set(df["public_client_id"]) <= set(pool)
    assert "<suppressed>" not in df["public_client_id"].tolist()


def test_two_files_share_pool_so_joins_have_overlap():
    col = {"sensitive": True, "categories": None}
    a = synthesize({"columns": {"public_client_id": col}}, n_rows=100, seed=1,
                   join_keys={"public_client_id"}, id_pool=[f"SYNTH_{i:04d}" for i in range(10)])
    b = synthesize({"columns": {"public_client_id": col}}, n_rows=100, seed=2,
                   join_keys={"public_client_id"}, id_pool=[f"SYNTH_{i:04d}" for i in range(10)])
    assert set(a["public_client_id"]) & set(b["public_client_id"])   # overlap -> joinable


def test_synthesize_without_join_keys_fabricates_not_suppresses():
    # without an id_pool/join_keys, sensitive columns are fabricated tokens, not "<suppressed>"
    col = {"sensitive": True, "categories": None}
    df = synthesize({"columns": {"public_client_id": col}}, n_rows=10)
    assert "<suppressed>" not in df["public_client_id"].tolist()
    assert all(str(v).startswith("FAKE_") for v in df["public_client_id"])


def test_sensitive_numeric_column_gets_fake_numbers(tmp_path):
    col = {"dtype": "float64", "n": 100, "pct_missing": 0.0, "cardinality": 100,
           "sensitive": True, "values_suppressed": True, "categories": None}
    df = synthesize({"columns": {"x": col}}, n_rows=30, seed=1)
    import pandas as pd
    assert pd.api.types.is_numeric_dtype(df["x"])          # numeric, not "<suppressed>" strings
    assert "<suppressed>" not in df["x"].astype(str).tolist()


def test_sensitive_date_column_gets_fake_dates():
    import re
    col = {"dtype": "object", "n": 100, "pct_missing": 0.0, "cardinality": 90,
           "sensitive": True, "categories": None}
    df = synthesize({"columns": {"collection_date": col}}, n_rows=30, seed=1)
    assert all(re.match(r"20\d\d-\d\d-\d\d", str(v)) for v in df["collection_date"])   # fabricated dates


def test_sensitive_text_id_gets_fake_token():
    col = {"dtype": "object", "n": 100, "pct_missing": 0.0, "cardinality": 100,
           "sensitive": True, "categories": None}
    df = synthesize({"columns": {"sample_id": col}}, n_rows=10, seed=1)
    assert all(str(v).startswith("FAKE_") for v in df["sample_id"])
