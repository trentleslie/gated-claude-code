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


def test_sensitive_column_is_placeholder():
    prof = profile_file(str(FX / "with_ids.csv"))
    df = synthesize(prof, n_rows=10)
    assert (df["email"] == "<suppressed>").all()


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


def test_empty_histogram_numeric_suppressed():
    fp = {"columns": {"c": {"dtype": "int64", "n": 50, "pct_missing": 0.0,
                            "cardinality": 1, "sensitive": False, "histogram": []}}}
    assert (synthesize(fp, n_rows=10)["c"] == "<suppressed>").all()
