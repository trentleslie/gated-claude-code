"""Per-column timestamp *format* descriptor (non-disclosive by construction).

The descriptor captures only format SHAPE — representation (ISO string / epoch),
granularity, separator, timezone kind, and a generalized strftime/regex template
built from format tokens alone. It NEVER embeds a literal value substring (R15),
so it is safe to persist into the dictionary and regenerate synthetic samples from.

Mixed-format columns keep the dominant format, record each distinct minority format
present in >= k subjects, and drop (suppress) any minority format present in < k
subjects — a rare format is itself a quasi-identifier (R3, R11, R15).
"""
import re
import pandas as pd
from ..config import DEFAULTS

# ISO-8601: date, optional [T| ]time, optional .subsecond, optional (Z|±offset).
_ISO = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:(?P<sep>[T ])(?P<time>\d{2}:\d{2}:\d{2})(?P<sub>\.\d+)?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?)?$"
)
_ALL_DIGITS = re.compile(r"^\d+$")
_DIGITS_DOT = re.compile(r"^\d+\.\d+$")
_NULLISH = {"", "nan", "nat", "none", "null"}


def _classify(value):
    """Map one raw cell to a format-signature dict, or None if unparseable/empty."""
    s = str(value).strip()
    if s.lower() in _NULLISH:
        return None
    if _ALL_DIGITS.match(s):
        # epoch: 13-digit is milliseconds, 10-digit (and shorter) is seconds.
        rep = "epoch_ms" if len(s) >= 12 else "epoch_s"
        return {"representation": rep, "granularity": "datetime",
                "separator": None, "timezone": "naive", "template": rep}
    if _DIGITS_DOT.match(s):
        return {"representation": "epoch_s", "granularity": "datetime_subsecond",
                "separator": None, "timezone": "naive", "template": "epoch_s_float"}
    m = _ISO.match(s)
    if m:
        if m.group("time") is None:
            return {"representation": "iso8601", "granularity": "date",
                    "separator": None, "timezone": "naive", "template": "%Y-%m-%d"}
        sep = m.group("sep")
        septok = "T" if sep == "T" else " "
        subsec = m.group("sub") is not None
        subtok = ".%f" if subsec else ""
        tz = m.group("tz")
        if tz is None:
            tzk, tztok = "naive", ""
        elif tz == "Z":
            tzk, tztok = "utc", "Z"
        else:
            tzk, tztok = "offset", "%z"
        return {"representation": "iso8601",
                "granularity": "datetime_subsecond" if subsec else "datetime",
                "separator": septok, "timezone": tzk,
                "template": f"%Y-%m-%d{septok}%H:%M:%S{subtok}{tztok}"}
    return {"representation": "other", "granularity": "unknown",
            "separator": None, "timezone": "unknown", "template": "other"}


def _is_value_free(template: str) -> bool:
    # R15: a safe template is built from format tokens only — no literal digit run.
    return not re.search(r"\d", template)


def detect_format(series, sid=None, thresholds=DEFAULTS):
    """Return a value-free format descriptor for a timestamp column, or None.

    ``sid`` (subject id column, index-aligned with ``series``) drives the k-anon
    subject count used to suppress rare minority formats. Without it, occurrence
    counts stand in for subject counts.
    """
    k = thresholds.k
    raw = series.dropna()
    if raw.empty:
        return None
    sigs = raw.astype(str).map(_classify)
    sigs = sigs[sigs.notna()]
    if sigs.empty:
        return None
    templates = sigs.map(lambda x: x["template"])
    by_template = {}
    for sig in sigs:
        by_template.setdefault(sig["template"], sig)

    order = templates.value_counts()          # by occurrence -> dominant is index[0]
    dominant = order.index[0]

    # subject count per distinct template + column-level contributor count (k-anon basis)
    if sid is not None:
        sid_al = pd.Series(sid).reindex(templates.index)
        frame = pd.DataFrame({"t": templates.values, "sid": sid_al.values})
        subj_count = {t: int(g["sid"].nunique(dropna=True)) for t, g in frame.groupby("t")}
        col_contrib = int(sid_al.nunique(dropna=True))
    else:
        subj_count = {t: int(c) for t, c in order.items()}
        col_contrib = int(templates.shape[0])      # occurrences stand in for subjects

    # R11/R15: gate the WHOLE descriptor, not just minority formats. A column
    # contributed by < k subjects discloses its representation/timezone/precision/
    # mixed-state as a quasi-identifier — suppress it entirely.
    if col_contrib < k:
        return None

    desc = dict(by_template[dominant])
    minority = [by_template[t] for t in order.index[1:] if subj_count.get(t, 0) >= k]
    desc["mixed"] = len(order) > 1
    if minority:
        desc["minority"] = minority

    # R15 defense-in-depth: never let a value-bearing template escape.
    for t in [desc["template"]] + [m["template"] for m in desc.get("minority", [])]:
        assert _is_value_free(t), f"format template is not value-free: {t}"
    return desc
