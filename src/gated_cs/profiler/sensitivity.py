import re, pandas as pd
from ..config import DEFAULTS
_NAME = re.compile(r"(email|mrn|ssn|dob|birth|name|address|zip|phone|geo|date|time|timestamp|_at$|_id$|^id$)", re.I)
_DATEVAL = re.compile(r"^\d{4}-\d{2}-\d{2}")

def is_sensitive(name, series, thresholds=DEFAULTS):
    if _NAME.search(name or ""):
        return True
    n = max(1, series.shape[0])
    if not pd.api.types.is_numeric_dtype(series):
        nn = series.dropna().astype(str)
        if not nn.empty and nn.nunique() / n > 0.9:      # near-unique -> identifier-like
            return True
        sample = nn.head(200)
        if len(sample) and sample.str.match(_DATEVAL).mean() >= 0.6:   # date-valued
            return True
    return False
