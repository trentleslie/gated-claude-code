import pandas as pd
from gated_cs.profiler.subject_key import detect_subject_key, cohort_n

def test_detect_prefers_specific_then_falls_back():
    assert detect_subject_key(["Subject_ID", "ts", "hr"]) == "Subject_ID"
    assert detect_subject_key(["ts", "user_id", "steps"]) == "user_id"
    assert detect_subject_key(["record_id", "public_client_id"]) == "public_client_id"
    assert detect_subject_key(["ts", "value"]) is None

def test_detect_prefers_time_traveler_id_over_record_id():
    # TIME study's real participant key; record_id is a per-row REDCap id, not per-person
    assert detect_subject_key(["time_traveler_id", "record_id", "_time"]) == "time_traveler_id"

def test_cohort_n_counts_distinct_nonnull():
    s = pd.Series(["a", "a", "b", None, "c", "c"])
    assert cohort_n(s) == 3
