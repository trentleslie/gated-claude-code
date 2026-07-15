import re, pandas as pd
from ..config import DEFAULTS
_NAME = re.compile(r"(email|mrn|ssn|dob|birth|name|address|zip|phone|geo|_id$|^id$)", re.I)

def is_sensitive(name, series, thresholds=DEFAULTS):
    if _NAME.search(name or ""):
        return True
    n = max(1, series.shape[0])
    if not pd.api.types.is_numeric_dtype(series) and series.nunique(dropna=True) / n > 0.9:
        return True
    return False
