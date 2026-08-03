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

# --- residual-risk hardening: small per-person tables must not auto-release (R1/R2/R3) ---

def test_near_unique_column_without_count_is_quarantined():
    # 10 rows, one distinct value per row, no count column -> per-person, must not auto-release
    df = pd.DataFrame({"note": [f"free text {i}" for i in range(10)]})
    v = check_table(df)
    assert v.status == "block"
    assert "per-person" in v.reason.lower()

def test_date_valued_column_without_count_is_quarantined():
    # a date-valued column (matches _DATEVAL) with no count column -> quarantine.
    # repeated dates keep it below the near-unique ratio so the DATE path is what fires.
    df = pd.DataFrame({"collected": ["2025-01-01", "2025-01-01", "2025-01-02",
                                     "2025-01-02", "2025-01-03", "2025-01-03"]})
    v = check_table(df)
    assert v.status == "block"
    assert "per-person" in v.reason.lower()

def test_combination_of_quasi_identifiers_is_quarantined():
    # coarse age band + coarse region: each individually passable (low-cardinality, not
    # near-unique), together re-identifying -> quarantine on the combination threshold
    df = pd.DataFrame({"age_band": ["30-40", "40-50", "30-40", "40-50"],
                       "region": ["West", "East", "West", "East"]})
    v = check_table(df)
    assert v.status == "block"
    assert "quasi-identifier" in v.reason.lower()

def test_single_low_cardinality_group_without_count_still_allows():
    # one coarse categorical column alone is below the combination threshold -> allow
    df = pd.DataFrame({"region": ["West", "East", "North", "West"]})
    assert check_table(df).status == "allow"

def test_small_genuine_aggregate_with_count_not_over_quarantined():
    # a 3-row aggregate: low-cardinality group + count column -> still allow (R7, no over-quarantine)
    df = pd.DataFrame({"region": ["West", "East", "North"], "count": [40, 55, 30]})
    assert check_table(df).status == "allow"

def test_date_valued_column_with_count_still_releases():
    # a time-series aggregate (date + count, all cells >= k) is unchanged: allow
    df = pd.DataFrame({"month": ["2025-01", "2025-02", "2025-03"], "count": [50, 60, 70]})
    assert check_table(df).status == "allow"

def test_empty_column_without_count_fails_closed():
    import numpy as np
    df = pd.DataFrame({"x": [np.nan, np.nan, np.nan]})
    v = check_table(df)   # must not crash
    assert v.status == "block"   # uninterpretable -> fail closed to human review

# --- Greptile P1 #1: a count column must not exempt a table from the per-person check ---

def test_count_column_does_not_bypass_per_person_check():
    # A near-unique per-person identifier column (participant_code, one distinct value per
    # row, >= k distinct) alongside a recognized count column (total) whose cells are all
    # >= k previously auto-released via the count branch WITHOUT any value-based sensitivity
    # check. The participant values still require human review -> quarantine.
    df = pd.DataFrame({"participant_code": [f"P{i:04d}" for i in range(8)],
                       "total": [10] * 8})
    v = check_table(df)
    assert v.status == "block"
    assert "per-person" in v.reason.lower()

def test_count_column_with_low_cardinality_group_still_allows():
    # regression guard for #1's fix: a genuine frequency table (low-cardinality group +
    # count, all cells >= k) must still auto-release -- the per-person check must not
    # over-quarantine legitimate aggregates.
    df = pd.DataFrame({"region": ["West", "East", "North"], "total": [40, 55, 30]})
    assert check_table(df).status == "allow"

# --- Greptile P1 #2: sub-k unique columns in a count-less table must quarantine ---

def test_sub_k_unique_column_without_count_is_quarantined():
    # A count-less table with fewer than k rows and one distinct non-date string per row is
    # a per-person micro-cohort. Being below the k-distinct floor makes it MORE identifying
    # (group size 1 < k), not less, so it must quarantine rather than auto-release.
    df = pd.DataFrame({"participant_code": ["P1", "P2", "P3", "P4"]})  # 4 rows, k=5
    v = check_table(df)
    assert v.status == "block"
    assert "per-person" in v.reason.lower()

def test_single_row_metric_aggregate_without_count_still_allows():
    # boundary guard for #2's fix: a 1-row metric/value summary is count-less and trivially
    # "unique per row" (nunique == 1) yet discloses no individual -> still auto-release.
    df = pd.DataFrame({"metric": ["mean_glucose"], "value": [5.4]})
    assert check_table(df).status == "allow"
