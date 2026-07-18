# Ranked most-specific first; detection returns the first candidate present.
SUBJECT_KEY_CANDIDATES = (
    "subject_id", "participant_id", "public_client_id",
    "user_id", "record_id", "id",
)

def detect_subject_key(columns):
    lower = {c.lower(): c for c in columns}
    for cand in SUBJECT_KEY_CANDIDATES:
        if cand in lower:
            return lower[cand]
    return None

def cohort_n(series):
    return int(series.nunique(dropna=True))
