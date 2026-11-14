import re, uuid, pandas as pd
from ..config import DEFAULTS
_NAME = re.compile(r"(email|mrn|ssn|dob|birth|name|address|zip|phone|geo|date|time|timestamp|_at$|_id$|^id$)", re.I)
_DATEVAL = re.compile(r"^\d{4}-\d{2}-\d{2}")
# The ONE definition of "UUID-shaped" (shared by the profiler, the dictionary build's
# published-output scan and the release gate). A value is UUID-shaped when it CONTAINS a
# UUID token, so braces, a `urn:uuid:` prefix, padding, quotes, `coach:<uuid>` and
# multi-valued cells are all covered. The hyphenated 8-4-4-4-12 form matches anywhere. The
# bare 32-hex form needs a non-hex character (or the string edge) on both sides, so longer
# hex strings such as a SHA-256 digest do not match.
UUID_TOKEN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", re.I)

def uuid_text(value):
    """Text the shape test reads. UUID objects and 16-byte binary values (how a native
    Parquet UUID / fixed-length binary column reaches pandas) are rendered in canonical
    form first; str() of raw bytes would be a byte-repr the pattern cannot see."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return str(uuid.UUID(bytes=raw)) if len(raw) == 16 else raw.decode("latin-1")
    return str(value)

def as_text(series):
    """series.astype(str) that also works for binary values: pandas raises on bytes that
    are not valid UTF-8 (most binary UUIDs) and would mis-render the rest. Only object
    columns that are not plain strings take the per-value path, where uuid_text equals
    str() for everything except bytes and UUID objects."""
    if series.dtype == object and pd.api.types.infer_dtype(series, skipna=True) != "string":
        return series.map(uuid_text)
    return series.astype(str)

def contains_uuid(value):
    if value is None or value is pd.NA:
        return False
    if isinstance(value, float) and value != value:   # NaN
        return False
    return bool(UUID_TOKEN.search(uuid_text(value)))

def uuid_mask(series):
    """Per-value contains_uuid as a plain boolean Series. Cast to object first: Series.map
    on a categorical column returns a Categorical whenever the mapping is one-to-one (a
    single-category column, or one UUID and one non-UUID category), and a Categorical
    supports neither any() nor mean()."""
    return series.astype(object).map(contains_uuid).astype(bool)

def is_sensitive(name, series, thresholds=DEFAULTS):
    if _NAME.search(name or ""):
        return True
    n = max(1, series.shape[0])
    if not pd.api.types.is_numeric_dtype(series):
        raw = series.dropna()
        nn = as_text(raw)
        # near-unique -> identifier-like, but only once there are at least k distinct values:
        # below the k-anonymity floor a column cannot fingerprint an individual, and on a tiny
        # aggregate (e.g. a metric/value summary) near-uniqueness is trivially true and benign.
        if not nn.empty and nn.nunique() >= thresholds.k \
                and nn.nunique() / n > thresholds.near_unique_ratio:
            return True
        sample = nn.head(200)
        if len(sample) and sample.str.match(_DATEVAL).mean() >= 0.6:   # date-valued
            return True
        # mostly UUID-valued (same bar and sampling as the date rule). Tested on the raw
        # values, not their str() form, so binary UUIDs are recognised.
        if len(raw) and uuid_mask(raw.head(200)).mean() >= 0.6:
            return True
    return False
