import pandas as pd, pathlib
from gated_cs.profiler.profile import profile_column, profile_file
FX = pathlib.Path(__file__).parent.parent / "fixtures"

def test_numeric_histogram_no_raw_minmax():
    s = pd.Series(list(range(100)))
    out = profile_column(s)
    assert out["dtype"].startswith("int")
    assert "histogram" in out and out["histogram"]
    assert all(b["count"] >= 5 for b in out["histogram"])
    assert "min" not in out and "max" not in out

def test_categorical_vocab_capped():
    s = pd.Series(["A", "B", "C"] * 40)
    out = profile_column(s)
    assert set(out["categories"]) == {"A", "B", "C"}

def test_high_cardinality_suppressed():
    s = pd.Series([f"id{i}" for i in range(200)])
    out = profile_column(s)
    assert out["categories"] is None and out["suppressed_high_cardinality"] is True

def test_profile_file_carries_descriptions():
    out = profile_file(str(FX / "simple.csv"))
    assert out["columns"]["age"]["description"] == "age in years"
