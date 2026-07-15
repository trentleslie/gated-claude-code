import pandas as pd
from gated_cs.profiler.sensitivity import is_sensitive
from gated_cs.profiler.profile import profile_column

def test_name_heuristic_flags_email():
    assert is_sensitive("email", pd.Series(["a@b.com"]))

def test_near_unique_flags_ids():
    assert is_sensitive("public_id", pd.Series([f"P{i}" for i in range(100)]))

def test_non_sensitive_category():
    assert not is_sensitive("sex", pd.Series(["M", "F"] * 50))

def test_profile_suppresses_sensitive_values():
    out = profile_column(pd.Series([f"user{i}@x.com" for i in range(100)]), name="email")
    assert out["sensitive"] is True
    assert out.get("values_suppressed") is True
    assert out.get("categories") in (None, [])
