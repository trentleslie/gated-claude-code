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


# --- UUID-shaped values (pre-rebuild hardening R2/R3) ---
import uuid
import pytest
from gated_cs.profiler.sensitivity import contains_uuid

_U = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"
_UUIDS = [str(uuid.UUID(int=(0xA5A5 << 96) + i * 0x1000000000001 + 7)) for i in range(10)]


@pytest.mark.parametrize("value", [
    _U,                                   # lowercase hyphenated
    _U.upper(),                           # uppercase hyphenated
    _U.replace("-", ""),                  # bare 32 hex
    _U.replace("-", "").upper(),
    "{" + _U + "}",                       # braced
    "urn:uuid:" + _U,                     # urn prefix
    " " + _U, _U + " ", _U + "\r",        # padded
    '"' + _U + '"', "'" + _U + "'",       # quoted
    "coach:" + _U,                        # prefixed
    _U + ";" + _UUIDS[0],                 # multi-valued
    "c" + _U,                             # hex-letter prefix must not hide a hyphenated UUID
    uuid.UUID(_U),                        # UUID object
    uuid.UUID(_U).bytes,                  # 16-byte binary
])
def test_uuid_shaped_values_detected(value):
    assert contains_uuid(value)


@pytest.mark.parametrize("value", [
    _U.replace("-", "")[:31],                                  # 31 hex characters
    "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6g",                    # non-hex character
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",  # SHA-256
    "", "unassigned", "A", None, float("nan"), pd.NA, 12345, 3.5,
])
def test_non_uuid_values_not_detected(value):
    assert not contains_uuid(value)


def test_uuid_valued_column_is_sensitive():
    # the Arivale `coach` case: 10 staff UUIDs, each on 10 rows; name matches no pattern
    assert is_sensitive("coach", pd.Series(_UUIDS * 10))


def test_binary_uuid_column_is_sensitive():
    assert is_sensitive("coach", pd.Series([uuid.UUID(u).bytes for u in _UUIDS] * 10))


def test_minority_uuid_column_not_flagged_by_column_rule():
    # 40% UUIDs / 60% placeholder is below the column bar; the per-value filter in
    # profile_column (not this rule) is what keeps those UUIDs unpublished.
    s = pd.Series(_UUIDS * 4 + ["unassigned"] * 60)
    assert not is_sensitive("coach", s)
