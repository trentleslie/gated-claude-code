import re
from dataclasses import dataclass
import pandas as pd
from ..config import DEFAULTS
from ..profiler.sensitivity import is_sensitive
_ID = re.compile(r"(email|mrn|ssn|dob|birth|name|address|zip|phone|geo|_id$|^id$)", re.I)

@dataclass
class Verdict:
    status: str
    reason: str
    safe_df: pd.DataFrame | None = None

_COUNT_TOKENS = {"count", "cnt", "n", "freq", "frequency", "size", "tally", "num", "total"}

def _count_col(df):
    for c in df.columns:
        tokens = set(re.split(r"[^a-z0-9]+", str(c).lower()))
        if _COUNT_TOKENS & tokens:
            return c
    return None

def _per_person_verdict(df, thresholds):
    """Residual-risk hardening: a table with NO recognized aggregate/count column that
    nonetheless carries per-person-looking columns must not auto-release. Reuse the
    profiler's richer quasi-identifier detector (near-unique / date-valued / identifier
    names) so there is one source of truth for "what looks like a person" (R1, R2). A
    combination of several individually-passable quasi-identifier columns is itself a
    re-identification risk (R3). Fail closed: any error classifying a column quarantines
    the artifact rather than releasing it. Returns a quarantine Verdict, or None if the
    table looks like a genuine count-less aggregate that may release.
    """
    sensitive, quasi = [], []
    for c in df.columns:
        name = str(c)
        try:
            col = df[c]
            if col.dropna().empty:
                # an all-NaN / empty column in a count-less table is uninterpretable —
                # cannot prove it is safe, so fail closed to human review.
                return Verdict("block", "per-person heuristic: uninterpretable empty column "
                                        f"{name!r} with no aggregate column, human review required")
            if is_sensitive(name, col, thresholds):
                sensitive.append(name)
            elif not pd.api.types.is_numeric_dtype(col):
                # a low-cardinality categorical (age band, region, sex, ...) is not
                # identifier-like alone, but co-occurring ones triangulate (R3).
                nun = int(col.nunique(dropna=True))
                if 1 < nun <= thresholds.cardinality_cap:
                    quasi.append(name)
        except Exception:
            # fail closed: an unclassifiable column quarantines, never releases.
            return Verdict("block", f"per-person heuristic: unclassifiable column {name!r}")
    if sensitive:
        return Verdict("block", "per-person quasi-identifier column(s) with no aggregate "
                                f"column, human review required: {sensitive}")
    if len(quasi) > thresholds.max_quasi_identifier_cols:
        return Verdict("block", f"{len(quasi)} co-occurring quasi-identifier columns with no "
                                f"aggregate column, human review required: {quasi}")
    return None

def check_table(df, thresholds=DEFAULTS):
    if len(df) > thresholds.row_cap:
        return Verdict("block", f"row count {len(df)} exceeds cap {thresholds.row_cap}")
    for c in df.columns:
        if _ID.search(str(c)):
            return Verdict("block", f"identifier-like column: {c}")
    cc = _count_col(df)
    if cc is not None:
        small = ~(df[cc] >= thresholds.k)   # NaN counts -> not >= k -> suppressed (fail-closed)
        if small.any():
            safe = df.loc[~small].reset_index(drop=True)
            return Verdict("suppress", f"suppressed {int(small.sum())} cells < k={thresholds.k}", safe)
        return Verdict("allow", "clean aggregate", df.reset_index(drop=True))
    # No recognized aggregate/count column: a genuine aggregate is signalled by that count
    # column, so a count-less table with per-person-looking columns must go to human review
    # instead of falling through to auto-release (residual risk 1).
    ppv = _per_person_verdict(df, thresholds)
    if ppv is not None:
        return ppv
    return Verdict("allow", "clean aggregate", df.reset_index(drop=True))
