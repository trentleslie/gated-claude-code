"""Synthetic-sample generator.

Two paths:

  * **Joint per-subject** (R17) — used when a join-key column is present AND at least
    one column carries a ``temporal_distribution`` facet. Each synthetic subject's
    rows are emitted as a coherent, time-ordered block: a per-subject timeline is
    drawn from the captured cohort distributions (cadence, sessions, gaps, diurnal,
    coverage), timestamps are rendered in the captured format (R7/R8), and value
    columns are co-located onto the same rows (R19).

  * **Legacy i.i.d.** — retained for facet-less profiles (derived layers, keyless
    files). Columns are filled independently. Timestamp columns that carry a value-
    free ``format`` facet are rendered format-correct within their captured month
    range instead of the old date-only random path.

All draws come from a single seeded RNG in fixed column/subject order, so output is
byte-identical for a given dictionary + seed (R10).
"""
import random, re
import pandas as pd

_DATE_NAME = re.compile(r"date|time|_at$|timestamp", re.I)

# Cohort cadence label -> representative seconds between consecutive stamps.
_CADENCE_SECONDS = {
    "~1/min or finer": 60,
    "~1/5 min": 300,
    "~1/15 min": 900,
    "~1/hour": 3600,
    "~1/6 hours": 21600,
    "~1/day": 86400,
    "~1/week": 604800,
    "~coarser than weekly": 1209600,
    "unknown": 3600,
}

_PER_SUBJECT_MIN = 24
_PER_SUBJECT_MAX = 48


# ---------------------------------------------------------------- rendering ----

def _render_ts(fmt, dt):
    """Render a pandas Timestamp per a (value-free) format descriptor."""
    ts = pd.Timestamp(dt)
    rep = fmt.get("representation")
    if rep == "epoch_ms":
        return str(ts.value // 1_000_000)
    if rep == "epoch_s":
        if fmt.get("template") == "epoch_s_float":
            return f"{ts.value / 1_000_000_000:.3f}"
        return str(ts.value // 1_000_000_000)
    date = ts.strftime("%Y-%m-%d")
    if fmt.get("granularity") == "date":
        return date
    sep = "T" if fmt.get("separator") == "T" else " "
    core = date + sep + ts.strftime("%H:%M:%S")
    if fmt.get("granularity") == "datetime_subsecond":
        core += f".{ts.microsecond:06d}"
    tz = fmt.get("timezone")
    if tz == "utc":
        core += "Z"
    elif tz == "offset":
        core += "+00:00"           # canonical offset; real per-value offset not disclosed
    return core


def _range(cov):
    if cov and cov.get("min_month"):
        start = pd.Timestamp(cov["min_month"] + "-01")
        end = pd.Timestamp(cov["max_month"] + "-01") + pd.offsets.MonthEnd(0)
    else:
        start, end = pd.Timestamp("2015-01-01"), pd.Timestamp("2020-12-31")
    return start, end


def _rand_dt(rng, cov):
    start, end = _range(cov)
    span = max(int((end - start).total_seconds()), 1)
    return start + pd.Timedelta(seconds=rng.randint(0, span))


def _pick_hour(rng, diurnal_blocks):
    if not diurnal_blocks:
        return rng.randint(0, 23)
    labels = list(diurnal_blocks)
    weights = [max(float(diurnal_blocks[l]), 0.0) for l in labels]
    if sum(weights) <= 0:
        return rng.randint(0, 23)
    label = rng.choices(labels, weights=weights, k=1)[0]
    a, b = (int(x) for x in label.split("-"))
    return rng.randint(a, max(a, b - 1))


# --------------------------------------------------------- value generation ----

def _draw_values(name, col, count, rng):
    dtype = str(col.get("dtype", ""))
    if "histogram" in col and col["histogram"]:
        bins = col["histogram"]
        chosen = rng.choices(bins, weights=[b["count"] for b in bins], k=count)
        vals = [rng.uniform(b["lo"], b["hi"]) for b in chosen]
        return [int(round(v)) for v in vals] if "int" in dtype.lower() else vals
    if col.get("categories"):
        return [rng.choice(col["categories"]) for _ in range(count)]
    if "int" in dtype or "float" in dtype:
        vals = [rng.uniform(0, 100) for _ in range(count)]
        return [int(round(v)) for v in vals] if "int" in dtype else [round(v, 3) for v in vals]
    if _DATE_NAME.search(name):        # sensitive date column with no captured format
        return ["20%02d-%02d-%02d" % (rng.randint(15, 20), rng.randint(1, 12), rng.randint(1, 28))
                for _ in range(count)]
    tag = re.sub(r"[^A-Za-z0-9]", "", name)[:8] or "col"
    return ["FAKE_%s_%04d" % (tag, rng.randint(0, 9999)) for _ in range(count)]


def _is_ts_col(col):
    return bool(col.get("format") or col.get("temporal_distribution"))


# ---------------------------------------------------------------- entry ----

def synthesize(file_profile, n_rows=100, seed=0, join_keys=(), id_pool=None):
    cols = file_profile["columns"]
    jk = set(join_keys)
    subject_col = next((n for n in cols if n in jk), None)
    ts_cols = [n for n, c in cols.items() if c.get("temporal_distribution")]
    if subject_col and id_pool and ts_cols:
        return _synthesize_joint(cols, n_rows, seed, subject_col, id_pool, ts_cols[0])
    return _synthesize_iid(cols, n_rows, seed, jk, id_pool)


def _synthesize_iid(cols, n_rows, seed, jk, id_pool):
    rng = random.Random(seed)
    data = {}
    for name, col in cols.items():
        if name in jk and id_pool:
            data[name] = [rng.choice(id_pool) for _ in range(n_rows)]
        elif col.get("format"):
            # format-correct fallback (never regress to date-only random)
            fmt, cov = col["format"], col.get("temporal_coverage")
            data[name] = [_render_ts(fmt, _rand_dt(rng, cov)) for _ in range(n_rows)]
        else:
            data[name] = _draw_values(name, col, n_rows, rng)
    return pd.DataFrame(data)


def _synthesize_joint(cols, n_rows, seed, subject_col, id_pool, primary_name):
    rng = random.Random(seed)
    primary = cols[primary_name]
    dist = primary.get("temporal_distribution") or {}
    cov = primary.get("temporal_coverage") or {}
    primary_fmt = primary.get("format") or {
        "representation": "iso8601", "granularity": "datetime",
        "separator": "T", "timezone": "utc"}
    minority = primary_fmt.get("minority", [])

    cadence_s = _CADENCE_SECONDS.get(dist.get("cadence"), 3600)
    min_start, max_end = _range(cov)
    total_days = max(1, (max_end - min_start).days)

    n_subjects = min(len(id_pool), max(2, n_rows // 30))
    subjects = id_pool[:n_subjects]
    blocks = {name: [] for name in cols}

    for si, sid in enumerate(subjects):
        r = rng.randint(_PER_SUBJECT_MIN, _PER_SUBJECT_MAX)
        n_sessions = min(rng.randint(2, 4), total_days + 1)
        day_offsets = sorted(rng.sample(range(total_days + 1), n_sessions))  # distinct -> gaps
        base, rem = divmod(r, n_sessions)
        dts = []
        for k_i, off in enumerate(day_offsets):
            npts = base + (1 if k_i < rem else 0)
            if npts <= 0:
                continue
            hour = _pick_hour(rng, dist.get("diurnal_blocks"))
            t0 = min_start + pd.Timedelta(days=off, hours=hour, minutes=rng.randint(0, 59))
            dts.extend(t0 + pd.Timedelta(seconds=cadence_s * i) for i in range(npts))
        dts = sorted(dts)
        # keep every subject's stamps inside the captured month range
        dts = [d for d in dts if d <= max_end] or [min_start]
        rr = len(dts)

        # per-subject format for the primary column so every RETAINED format is emitted
        # (a < k minority was already dropped from the descriptor and never reappears).
        subj_primary_fmt = primary_fmt
        if minority and 1 <= si <= len(minority):
            subj_primary_fmt = minority[si - 1]

        for name, col in cols.items():
            if name == subject_col:
                blocks[name].extend([sid] * rr)
            elif _is_ts_col(col):
                fmt = subj_primary_fmt if name == primary_name else (col.get("format") or primary_fmt)
                blocks[name].extend(_render_ts(fmt, d) for d in dts)
            else:
                blocks[name].extend(_draw_values(name, col, rr, rng))
    return pd.DataFrame(blocks)
