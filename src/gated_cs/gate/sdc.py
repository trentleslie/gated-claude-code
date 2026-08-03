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

def _per_person_verdict(df, thresholds, has_count=False, count_col=None):
    """Residual-risk hardening: a table that carries per-person-looking columns must not
    auto-release. Reuse the profiler's richer quasi-identifier detector (near-unique /
    date-valued / identifier names) so there is one source of truth for "what looks like a
    person" (R1, R2). A combination of several individually-passable quasi-identifier
    columns is itself a re-identification risk (R3). Fail closed: any error classifying a
    column quarantines the artifact rather than releasing it. Returns a quarantine Verdict,
    or None if the table looks like a genuine aggregate that may release.

    This runs on BOTH release paths. On a count-BEARING table a recognized count column is
    the aggregate signal, so its own values are the counts (skipped here), low-cardinality
    grouping labels may legitimately be near-unique, and numeric columns are legitimately
    per-group statistics (a distinct mean per group is near-unique yet safe) -- so near
    uniqueness there cannot distinguish a per-person id from an aggregate and naming is the
    tool. On a count-LESS table there is no aggregate signal, so a column that is (near-)unique
    per row is a per-person micro-table REGARDLESS OF DTYPE -- a numeric per-person id or raw
    measurement is as identifying as a string code (Greptile P1 numeric bypass) -- and it
    quarantines even below the k-distinct floor: sub-k uniqueness is the worst case (group
    size 1 < k), not a safe one (Greptile P1 #1 / #2). nunique == 1 (a constant / 1-row
    summary) discloses no individual and still releases.
    """
    sensitive, quasi = [], []
    for c in df.columns:
        name = str(c)
        if has_count and c == count_col:
            continue   # the count column is the aggregate signal, not a quasi-identifier
        try:
            col = df[c]
            if col.dropna().empty:
                # an all-NaN / empty non-count column is uninterpretable — cannot prove it
                # is safe, so fail closed to human review.
                return Verdict("block", "per-person heuristic: uninterpretable empty column "
                                        f"{name!r}, human review required")
            if is_sensitive(name, col, thresholds):
                sensitive.append(name)
                continue
            nun = int(col.nunique(dropna=True))
            nrows = int(col.dropna().shape[0])
            if (not has_count and nun >= 2 and nrows
                    and nun / nrows > thresholds.near_unique_ratio):
                # count-less + (near-)unique-per-row column of ANY dtype -> per-person
                # micro-table. is_sensitive only inspects strings (near-unique / date /
                # name); a numeric per-person id or measurement slips past it, so catch it
                # here where the count-less context makes uniqueness unambiguously identifying.
                sensitive.append(name)
            elif not pd.api.types.is_numeric_dtype(col) and 1 < nun <= thresholds.cardinality_cap:
                # a low-cardinality categorical (age band, region, sex, ...) is not
                # identifier-like alone, but co-occurring ones triangulate (R3). Numeric
                # columns are values/statistics, not grouping quasi-identifiers.
                quasi.append(name)
        except Exception:
            # fail closed: an unclassifiable column quarantines, never releases.
            return Verdict("block", f"per-person heuristic: unclassifiable column {name!r}")
    if sensitive:
        return Verdict("block", "per-person quasi-identifier column(s), "
                                f"human review required: {sensitive}")
    if len(quasi) > thresholds.max_quasi_identifier_cols:
        return Verdict("block", f"{len(quasi)} co-occurring quasi-identifier columns, "
                                f"human review required: {quasi}")
    return None

def check_table(df, thresholds=DEFAULTS):
    if len(df) > thresholds.row_cap:
        return Verdict("block", f"row count {len(df)} exceeds cap {thresholds.row_cap}")
    for c in df.columns:
        if _ID.search(str(c)):
            return Verdict("block", f"identifier-like column: {c}")
    cc = _count_col(df)
    if cc is not None:
        # A count column signals an aggregate, but does NOT exempt the OTHER columns from
        # the per-person check: a near-unique identifier (e.g. participant_code) alongside a
        # count column must still quarantine, not release (Greptile P1 #1).
        ppv = _per_person_verdict(df, thresholds, has_count=True, count_col=cc)
        if ppv is not None:
            return ppv
        small = ~(df[cc] >= thresholds.k)   # NaN counts -> not >= k -> suppressed (fail-closed)
        if small.any():
            safe = df.loc[~small].reset_index(drop=True)
            return Verdict("suppress", f"suppressed {int(small.sum())} cells < k={thresholds.k}", safe)
        return Verdict("allow", "clean aggregate", df.reset_index(drop=True))
    # No recognized aggregate/count column: a genuine aggregate is signalled by that count
    # column, so a count-less table with per-person-looking columns must go to human review
    # instead of falling through to auto-release (residual risk 1).
    ppv = _per_person_verdict(df, thresholds, has_count=False)
    if ppv is not None:
        return ppv
    return Verdict("allow", "clean aggregate", df.reset_index(drop=True))
