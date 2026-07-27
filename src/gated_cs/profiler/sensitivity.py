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
        # near-unique -> identifier-like, but only once there are at least k distinct values:
        # below the k-anonymity floor a column cannot fingerprint an individual, and on a tiny
        # aggregate (e.g. a metric/value summary) near-uniqueness is trivially true and benign.
        if not nn.empty and nn.nunique() >= thresholds.k \
                and nn.nunique() / n > thresholds.near_unique_ratio:
            return True
        sample = nn.head(200)
        if len(sample) and sample.str.match(_DATEVAL).mean() >= 0.6:   # date-valued
            return True
    return False
