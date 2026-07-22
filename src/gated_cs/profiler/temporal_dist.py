"""Cohort temporal-structure distributions, engineered non-disclosive.

For a *longitudinal* timestamp column (many stamps per subject), capture k-safe
COHORT aggregates describing how subjects' timelines are shaped — cadence, session
lengths, inter-session gaps, diurnal activity, and enrollment-relative coverage.

Non-disclosure controls (all reuse the single SDC bar in ``Thresholds``):
  * R11 k-gate     — a distribution is emitted only if >= k subjects contribute to
                     THIS column (per-column contributor count, not file cohort_n).
  * R12 tail-clip  — histogram inputs are clipped to the 5th/95th percentile (never
                     to literal min/max, which would re-expose an outlier's extreme)
                     and each retained bin needs >= bin_min_count.
  * R13 coarsen    — diurnal activity is bucketed into ``diurnal_block_hours`` blocks.
  * R14 relative   — coverage is measured as a per-subject span/rate, never an
                     absolute calendar date.
  * R16 ephemeral  — per-subject runs/gaps/spans live only as function-local values
                     and are collapsed to cohort aggregates before returning; the
                     single-event guard skips columns with ~one stamp per subject.

Nothing per-subject is returned, printed, logged, or cached.
"""
import numpy as np
import pandas as pd
from .temporal import bucket_cadence
from ..config import DEFAULTS

# A delta larger than this multiple of a subject's own median cadence starts a new
# session (and counts as an inter-session gap).
_SESSION_GAP_FACTOR = 4.0
# Single-event tolerance: n_timestamps <= this * contributor_n => not longitudinal.
_SINGLE_EVENT_TOL = 1.1


def _clip_hist(pairs, thresholds):
    """Percentile-clipped, nice-edge histogram over (value, subject_id) pairs.

    A bin is disclosed only if it has BOTH >= bin_min_count events AND >= k distinct
    contributing subjects (R11/R12). The subject gate matters because one subject can
    emit many sessions/gaps: an event-count-only gate lets a bin clear the bar while
    representing 1-4 people, disclosing their timing pattern (found by the offline
    re-id gate on real data, 2026-07-22)."""
    from .profile import _nice_edges     # lazy: profile imports this module at top
    arr = [(float(x), s) for x, s in pairs if np.isfinite(x)]
    if len(arr) < 2:
        return []
    v = np.array([x for x, _ in arr], dtype=float)
    sids = np.array([s for _, s in arr], dtype=object)
    if np.unique(v).size < 2:
        return []
    lo, hi = float(np.percentile(v, 5)), float(np.percentile(v, 95))
    if hi <= lo:
        return []
    m = (v >= lo) & (v <= hi)
    v, sids = v[m], sids[m]
    if v.size < 2 or np.unique(v).size < 2:
        return []
    edges = _nice_edges(lo, hi, thresholds)
    idx = pd.cut(pd.Series(v), bins=edges, include_lowest=True, right=False)
    out = []
    for interval in idx.cat.categories:
        sel = (idx == interval).to_numpy()
        cnt = int(sel.sum())
        nsub = int(pd.unique(sids[sel]).size)
        if cnt >= thresholds.bin_min_count and nsub >= thresholds.k:
            out.append({"lo": round(float(interval.left), 4),
                        "hi": round(float(interval.right), 4),
                        "count": cnt, "n_subjects": nsub})
    return out


def temporal_distribution(df, name, subject_key, thresholds=DEFAULTS, ts_values=None):
    # ``ts_values`` (parsed datetime64, aligned to df) is supplied by the caller for
    # epoch-numeric columns, which the default format="mixed" parse cannot decode.
    if ts_values is None:
        ts_values = pd.to_datetime(df[name], errors="coerce", utc=True, format="mixed").values
    # Subject-aligned frame (NOT a head-slice) so large files aren't truncated/distorted.
    frame = pd.DataFrame({
        "sid": df[subject_key].values,
        "ts": ts_values,
    }).dropna(subset=["ts"])
    if frame.empty:
        return None

    contributor_n = int(frame["sid"].nunique(dropna=True))
    n_timestamps = int(frame.shape[0])
    if contributor_n < thresholds.k:
        return None                                   # R11 k-gate
    if n_timestamps <= _SINGLE_EVENT_TOL * contributor_n:
        return None                                   # R16 single-event guard

    block_w = thresholds.diurnal_block_hours
    n_blocks = 24 // block_w
    diurnal_counts = np.zeros(n_blocks, dtype=float)
    diurnal_contrib = np.zeros(n_blocks, dtype=int)   # distinct subjects per block (R11/R13)

    per_subject_medians = []            # for cohort cadence label
    session_pairs = []                 # (value, sid) — ephemeral, collapsed + subject-gated below
    gap_pairs = []
    coverage_pairs = []
    active_day_rates = []

    for sid_val, g in frame.groupby("sid", sort=False):
        ts = pd.Series(pd.to_datetime(g["ts"])).sort_values().reset_index(drop=True)
        # diurnal: count events, and track distinct-subject contribution per block so a
        # block filled by a single subject (their unique activity window) can be suppressed.
        hours = ts.dt.hour.to_numpy()
        subj_blocks = set()
        for h in hours:
            b = int(h) // block_w
            diurnal_counts[b] += 1
            subj_blocks.add(b)
        for b in subj_blocks:
            diurnal_contrib[b] += 1
        # enrollment-relative coverage
        span_days = (ts.iloc[-1] - ts.iloc[0]).total_seconds() / 86400.0
        active_days = ts.dt.normalize().nunique()
        coverage_pairs.append((span_days, sid_val))
        active_day_rates.append(active_days / (span_days + 1.0) if span_days >= 0 else 1.0)
        if ts.shape[0] < 2:
            continue
        deltas = ts.diff().dropna().dt.total_seconds().to_numpy()
        med = float(np.median(deltas))
        if np.isfinite(med) and med > 0:
            per_subject_medians.append(med)
        gap_break = max(_SESSION_GAP_FACTOR * med, 1.0) if med > 0 else np.inf
        # sessions = runs split at deltas exceeding gap_break
        session_start = 0
        for i, d in enumerate(deltas):
            if d > gap_break:
                gap_pairs.append((d / 3600.0, sid_val))
                seg = ts.iloc[session_start:i + 1]
                session_pairs.append(((seg.iloc[-1] - seg.iloc[0]).total_seconds() / 60.0, sid_val))
                session_start = i + 1
        seg = ts.iloc[session_start:]
        session_pairs.append(((seg.iloc[-1] - seg.iloc[0]).total_seconds() / 60.0, sid_val))

    cohort_cadence = bucket_cadence(
        float(np.median(per_subject_medians)) if per_subject_medians else None)
    # R11/R13: suppress any block with < k contributing subjects (a singleton block
    # reveals one subject's unique activity window), then normalize over survivors.
    diurnal_counts[diurnal_contrib < thresholds.k] = 0.0
    total = diurnal_counts.sum()
    diurnal_blocks = {
        f"{b * block_w:02d}-{(b + 1) * block_w:02d}":
            round(float(diurnal_counts[b] / total), 6) if total else 0.0
        for b in range(n_blocks)
    }

    return {
        "n_contributors": contributor_n,
        "cadence": cohort_cadence,
        "session_minutes": _clip_hist(session_pairs, thresholds),
        "gap_hours": _clip_hist(gap_pairs, thresholds),
        "diurnal_blocks": diurnal_blocks,
        "coverage_days": _clip_hist(coverage_pairs, thresholds),
        "active_day_rate": round(float(np.mean(active_day_rates)), 4) if active_day_rates else 0.0,
    }
