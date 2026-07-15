import pandas as pd
from gated_cs.gate.sdc import check_table

def test_blocks_row_dump():
    df = pd.DataFrame({"x": range(100)})
    v = check_table(df)
    assert v.status == "block" and "row" in v.reason.lower()

def test_blocks_identifier_column():
    df = pd.DataFrame({"email": ["a@b.com"], "n": [10]})
    v = check_table(df)
    assert v.status == "block"

def test_suppresses_small_cells():
    df = pd.DataFrame({"group": ["a", "b"], "count": [100, 3]})
    v = check_table(df)
    assert v.status in ("allow", "suppress")
    assert 3 not in v.safe_df["count"].tolist()  # n<5 removed/masked

def test_allows_clean_aggregate():
    df = pd.DataFrame({"group": ["a", "b"], "count": [100, 80]})
    v = check_table(df)
    assert v.status == "allow"

def test_count_column_alias_is_suppressed():
    # a count column NOT literally named "count" must still trigger k-suppression
    df = pd.DataFrame({"group": ["a", "b"], "n_patients": [100, 2]})
    v = check_table(df)
    assert v.status == "suppress"
    assert 2 not in v.safe_df["n_patients"].tolist()

def test_sample_size_alias_is_suppressed():
    df = pd.DataFrame({"cohort": ["x", "y"], "sample_size": [50, 1]})
    v = check_table(df)
    assert v.status == "suppress"
    assert 1 not in v.safe_df["sample_size"].tolist()

def test_nan_count_is_suppressed_fail_closed():
    import numpy as np
    df = pd.DataFrame({"group": ["a", "b"], "count": [80, np.nan]})
    v = check_table(df)
    assert v.status == "suppress"
    assert len(v.safe_df) == 1   # the NaN-count row is dropped

def test_row_count_exactly_at_cap_is_not_blocked():
    df = pd.DataFrame({"val": range(20)})   # == row_cap (20), no count/id column
    assert check_table(df).status == "allow"

def test_oversized_and_identifier_both_block():
    df = pd.DataFrame({"email": [f"u{i}@x.com" for i in range(30)]})
    assert check_table(df).status == "block"   # ordering: blocks regardless of which rule fires first
