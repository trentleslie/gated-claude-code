import re
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.format_detect import detect_format


def _sid(n_per, n_subj):
    return pd.Series([f"S{s:03d}" for s in range(n_subj) for _ in range(n_per)])


# ---- happy path: each representation/tz/granularity classified correctly ----

def test_iso_utc_z():
    s = pd.Series([f"2025-01-01T0{h}:00:00Z" for h in range(6)])
    d = detect_format(s)
    assert d["representation"] == "iso8601"
    assert d["timezone"] == "utc"
    assert d["granularity"] == "datetime"
    assert d["separator"] == "T"
    assert d["template"] == "%Y-%m-%dT%H:%M:%SZ"
    assert d["mixed"] is False


def test_iso_offset():
    s = pd.Series([f"2025-01-01T0{h}:00:00-08:00" for h in range(6)])
    d = detect_format(s)
    assert d["timezone"] == "offset"
    assert "%z" in d["template"]


def test_space_separated_datetime():
    s = pd.Series([f"2025-03-0{d} 12:00:00" for d in range(1, 6)])
    d = detect_format(s)
    assert d["separator"] == " "
    assert d["timezone"] == "naive"
    assert d["template"] == "%Y-%m-%d %H:%M:%S"


def test_date_only():
    s = pd.Series([f"2025-03-0{d}" for d in range(1, 6)])
    d = detect_format(s)
    assert d["granularity"] == "date"
    assert d["template"] == "%Y-%m-%d"
    assert d["timezone"] == "naive"


def test_epoch_seconds():
    s = pd.Series([str(1700000000 + i) for i in range(6)])
    d = detect_format(s)
    assert d["representation"] == "epoch_s"


def test_epoch_millis():
    s = pd.Series([str(1700000000000 + i) for i in range(6)])
    d = detect_format(s)
    assert d["representation"] == "epoch_ms"


def test_naive_local_no_offset_invented():
    s = pd.Series(["2025-01-01T00:00:00" for _ in range(6)])
    d = detect_format(s)
    assert d["timezone"] == "naive"
    assert "%z" not in d["template"] and "Z" not in d["template"]


# ---- mixed dominant + minority ----

def test_mixed_dominant_and_retained_minority():
    # 8 subjects dominant (Z), 6 subjects minority offset -> minority >= k retained
    dom = [f"2025-01-01T00:00:0{i}Z" for i in range(8) for _ in range(3)]
    minority = [f"2025-01-01T00:00:0{i}-08:00" for i in range(6) for _ in range(3)]
    s = pd.Series(dom + minority)
    sid = pd.Series([f"D{i:03d}" for i in range(8) for _ in range(3)]
                    + [f"M{i:03d}" for i in range(6) for _ in range(3)])
    d = detect_format(s, sid=sid, thresholds=DEFAULTS)
    assert d["mixed"] is True
    assert d["timezone"] == "utc"                    # dominant
    templates = [d["template"]] + [m["template"] for m in d.get("minority", [])]
    assert any("%z" in t for t in templates)         # retained minority present


def test_minority_below_k_suppressed():
    # dominant present in many subjects; minority format in only 2 subjects (< k=5)
    dom = [f"2025-01-01T00:00:0{i}Z" for i in range(10) for _ in range(3)]
    minority = ["2025-01-01 00:00:00" for _ in range(6)]  # only 2 subjects
    s = pd.Series(dom + minority)
    sid = pd.Series([f"D{i:03d}" for i in range(10) for _ in range(3)]
                    + ["M000", "M000", "M000", "M001", "M001", "M001"])
    d = detect_format(s, sid=sid, thresholds=DEFAULTS)
    assert d["mixed"] is True
    minority_templates = [m["template"] for m in d.get("minority", [])]
    assert "%Y-%m-%d %H:%M:%S" not in minority_templates   # suppressed (< k subjects)


# ---- R15 safety: template is value-free ----

def test_template_has_no_literal_value_digits():
    s = pd.Series([f"2025-01-0{d}T00:00:0{d}Z" for d in range(1, 6)])
    d = detect_format(s)
    all_templates = [d["template"]] + [m["template"] for m in d.get("minority", [])]
    for t in all_templates:
        assert not re.search(r"\d", t), f"template leaks literal digits: {t}"


def test_empty_column_returns_none():
    assert detect_format(pd.Series([None, None], dtype="object")) is None
