import pandas as pd, pathlib, numpy as np
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
    # cardinality (100) exceeds cardinality_cap (50) but ratio (0.5) stays below the
    # sensitivity near-uniqueness threshold (0.9), isolating this from Task 4's
    # identifier heuristic so it still exercises the plain cap-suppression path.
    s = pd.Series([f"id{i % 100}" for i in range(200)])
    out = profile_column(s)
    assert out["categories"] is None and out["suppressed_high_cardinality"] is True

def test_profile_file_carries_descriptions():
    out = profile_file(str(FX / "simple.csv"))
    assert out["columns"]["age"]["description"] == "age in years"

def test_histogram_edges_grid_aligned_no_raw_max():
    s = pd.Series(range(100))          # min 0, max 99
    hist = profile_column(s)["histogram"]
    assert hist
    edges = sorted({b["lo"] for b in hist} | {b["hi"] for b in hist})
    step = edges[1] - edges[0]
    for e in edges:                    # every edge is a multiple of the step (grid-aligned)
        assert abs(e / step - round(e / step)) < 1e-9
    assert 99.0 not in edges           # exact raw max never an edge
    assert all(b["count"] >= 5 for b in hist)

def test_histogram_rare_outlier_value_not_an_edge():
    s = pd.Series([1] * 95 + [104] * 5)   # outlier count == bin_min_count, bin NOT suppressed
    hist = profile_column(s)["histogram"]
    edges = {b["lo"] for b in hist} | {b["hi"] for b in hist}
    assert 104.0 not in edges          # precise outlier never disclosed via a bin edge

def test_histogram_all_bins_suppressed_is_empty():
    s = pd.Series([1, 2, 3, 4])         # each unique, every bin count < k=5
    assert profile_column(s)["histogram"] == []

def test_categorical_cap_boundary():
    # Same isolation as above: keep cardinality at/over the cap while keeping the
    # uniqueness ratio below Task 4's 0.9 sensitivity threshold via repeats.
    # Each category has >= k=5 rows so k-anonymity suppression doesn't interfere
    # with this cardinality-cap boundary test.
    at_cap = profile_column(pd.Series([f"c{i % 50}" for i in range(250)]))
    assert at_cap["categories"] is not None and len(at_cap["categories"]) == 50
    over_cap = profile_column(pd.Series([f"c{i % 51}" for i in range(255)]))
    assert over_cap["categories"] is None and over_cap["suppressed_high_cardinality"] is True

def test_constant_column_emits_no_histogram():
    # a column where every row is identical would pin the shared value via any bin -> emit nothing
    out = profile_column(pd.Series([5.0] * 50))
    assert out["histogram"] == []

def test_rare_categories_suppressed_below_k():
    # a category with fewer than k rows must not appear in the vocabulary
    s = pd.Series(["common"] * 95 + ["rare"] * 3 + ["mid"] * 2)  # rare=3, mid=2, both < k=5
    out = profile_column(s)
    assert "common" in out["categories"]
    assert "rare" not in out["categories"] and "mid" not in out["categories"]
    assert out["rare_categories_suppressed"] == 2

def test_histogram_handles_non_finite_values():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, np.inf, -np.inf])  # inf must not crash
    out = profile_column(s)              # must not raise OverflowError
    hist = out["histogram"]
    # all emitted bin edges are finite (no inf leaked into the histogram)
    for b in hist:
        assert np.isfinite(b["lo"]) and np.isfinite(b["hi"])

def test_hash_prefixed_column_name_is_not_comment_stripped(tmp_path):
    # QIIME-style: a column literally named '#OTUs' must survive (comment='#' would drop it)
    p = tmp_path / "otu.tsv"
    p.write_text("# ARIVALE SNAPSHOT\n# name: otu\nclient\t#OTUs\tcount\n"
                 "c1\totuA\t7\nc2\totuB\t9\nc3\totuA\t4\n")
    out = profile_file(str(p))
    assert set(out["columns"]) == {"client", "#OTUs", "count"}   # all 3 kept, none comment-stripped
