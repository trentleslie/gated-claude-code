from gated_cs.config import DEFAULTS, Thresholds
def test_defaults():
    assert DEFAULTS == Thresholds(k=5, row_cap=20, cardinality_cap=50, bin_min_count=5)
