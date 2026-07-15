import re
from dataclasses import dataclass
import pandas as pd
from ..config import DEFAULTS
_ID = re.compile(r"(email|mrn|ssn|dob|birth|name|address|zip|phone|geo|_id$|^id$)", re.I)

@dataclass
class Verdict:
    status: str
    reason: str
    safe_df: pd.DataFrame | None = None

def _count_col(df):
    for c in df.columns:
        if c.lower() in ("count", "n", "freq", "size"):
            return c
    return None

def check_table(df, thresholds=DEFAULTS):
    if len(df) > thresholds.row_cap:
        return Verdict("block", f"row count {len(df)} exceeds cap {thresholds.row_cap}")
    for c in df.columns:
        if _ID.search(str(c)):
            return Verdict("block", f"identifier-like column: {c}")
    cc = _count_col(df)
    if cc is not None:
        small = df[cc] < thresholds.k
        if small.any():
            safe = df.loc[~small].reset_index(drop=True)
            return Verdict("suppress", f"suppressed {int(small.sum())} cells < k={thresholds.k}", safe)
    return Verdict("allow", "clean aggregate", df.reset_index(drop=True))
