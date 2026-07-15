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

def test_date_column_by_name_is_sensitive():
    assert is_sensitive("BATCH_DATE", pd.Series(["2016-05-27", "2016-09-14"] * 10))
    assert is_sensitive("collection_date", pd.Series(["2017-01-01"] * 5))

def test_date_valued_column_is_sensitive_even_without_date_name():
    # column named innocuously but holding dates
    assert is_sensitive("visit", pd.Series(["2016-05-27", "2017-09-14", "2018-03-22"] * 5))

def test_non_date_category_not_flagged():
    assert not is_sensitive("sex", pd.Series(["M", "F"] * 50))
