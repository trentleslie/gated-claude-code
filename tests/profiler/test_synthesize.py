import pathlib
from gated_cs.profiler.profile import profile_file
from gated_cs.profiler.synthesize import synthesize

FX = pathlib.Path(__file__).parent.parent / "fixtures"


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
