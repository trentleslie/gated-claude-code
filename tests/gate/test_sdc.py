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
