"""Unit 8 — mechanical non-disclosure + triangulation gate.

These tests lock the *mechanical* SDC controls (leak / k-anon / bin / percentile /
ephemerality / <k-format / triangulation-smoke) as CI release blockers. They verify
the controls FIRE on synthetic-raw fixtures. They are NOT the real-cohort
re-identification proof — that is the deferred offline gated assessment.
"""
import io
import json
import os
import re
import glob
import contextlib
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.build_dictionary import build

# a value only the single outlier subject exhibits — must never reach any artifact
_OUTLIER_TOKEN = "OUTLIER_SUBJECT"
_OUTLIER_SUBSECOND = ".987654"


def _mk_time(tmp_path):
    base = tmp_path / "TIME"
    (base / "oura_ring").mkdir(parents=True)
    (base / "redcap").mkdir(parents=True)

    rows = []
    # 12 dominant subjects: ISO-Z, 5 days x 6 stamps/day, active mornings
    for s in range(12):
        for d in range(5):
            for h in range(6):
                dt = pd.Timestamp("2025-01-01") + pd.Timedelta(days=d, hours=8 + h)
                rows.append({"subject_id": f"S{s:03d}",
                             "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "hr": 60 + (h % 20)})
    # 6 subjects with a RETAINED minority format (space-separated) -> >= k
    for s in range(6):
        for d in range(5):
            dt = pd.Timestamp("2025-01-08") + pd.Timedelta(days=d, hours=10)
            rows.append({"subject_id": f"M{s:03d}",
                         "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"), "hr": 65})
    # 1 OUTLIER subject: a unique subsecond format (< k) AND a lone 3am diurnal slot
    for d in range(5):
        dt = pd.Timestamp("2025-01-15") + pd.Timedelta(days=d, hours=3)
        rows.append({"subject_id": _OUTLIER_TOKEN,
                     "timestamp": dt.strftime("%Y-%m-%dT%H:%M:%S.%f"), "hr": 200})
    pd.DataFrame(rows).to_csv(base / "oura_ring" / "TIME_oura_hr.csv", index=False)

    # demographics: DOB (birth quasi-identifier) + a single-event enroll date
    demo = pd.DataFrame({
        "subject_id": [f"S{s:03d}" for s in range(12)],
        "date_of_birth": ["1990-07-15"] * 12,
        "enroll_date": [f"2024-1{(s % 2)+1}-0{(s % 9)+1}" for s in range(12)],
        "sex": ["F"] * 6 + ["M"] * 6,
    })
    demo.to_csv(base / "redcap" / "TIME_demographics.csv", index=False)
    return str(base)


def _artifacts(out):
    dict_json = open(os.path.join(out, "dictionary.json")).read()
    md = open(os.path.join(out, "dictionary.md")).read()
    synth = "".join(open(p).read() for p in
                    glob.glob(os.path.join(out, "synthetic_samples", "**", "*.csv"), recursive=True))
    return dict_json, md, synth


def test_leak_free_across_all_three_artifacts(tmp_path):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path), out_dir=out, thresholds=DEFAULTS)
    dict_json, md, synth = _artifacts(out)
    blob = dict_json + md + synth
    # no real subject ids
    assert _OUTLIER_TOKEN not in blob
    assert "S000" not in blob and "M000" not in blob
    # no raw birth date / birth month
    assert "1990-07-15" not in blob and "1990-07" not in blob


def test_below_k_minority_format_never_disclosed(tmp_path):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path), out_dir=out, thresholds=DEFAULTS)
    dict_json, md, synth = _artifacts(out)
    blob = dict_json + md + synth
    d = json.load(open(os.path.join(out, "dictionary.json")))
    ts = d["files"][os.path.join("oura_ring", "TIME_oura_hr.csv")]["columns"]["timestamp"]
    templates = [ts["format"]["template"]] + [m["template"] for m in ts["format"].get("minority", [])]
    # the < k subsecond format is neither in the descriptor nor rendered anywhere
    assert not any(".%f" in t for t in templates)
    assert _OUTLIER_SUBSECOND not in blob
    assert not re.search(r"\.\d{6}", synth)


def test_below_k_subgroup_distribution_suppressed(tmp_path):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path), out_dir=out, thresholds=DEFAULTS)
    d = json.load(open(os.path.join(out, "dictionary.json")))
    cols = d["files"][os.path.join("redcap", "TIME_demographics.csv")]["columns"]
    # DOB is a birth quasi-identifier -> no temporal facets at all
    assert "temporal_coverage" not in cols["date_of_birth"]
    assert "temporal_distribution" not in cols["date_of_birth"]
    # single-event enroll date -> no distribution captured (R16)
    assert "temporal_distribution" not in cols["enroll_date"]


def test_per_subject_intermediates_never_persist(tmp_path):
    out = str(tmp_path / "out")
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        build(_mk_time(tmp_path), out_dir=out, thresholds=DEFAULTS)
    logged = buf_out.getvalue() + buf_err.getvalue()
    # nothing per-subject printed/logged during the build
    assert _OUTLIER_TOKEN not in logged
    assert "S000" not in logged and "1990-07-15" not in logged
    # no stray intermediate file under out_dir carries a real subject id / raw stamp
    expected_top = {"dictionary.json", "dictionary.md", "run_manifest.json", "synthetic_samples"}
    assert set(os.listdir(out)) <= expected_top, "unexpected intermediate written to out_dir"
    for p in glob.glob(os.path.join(out, "**", "*"), recursive=True):
        if os.path.isfile(p):
            txt = open(p, "rb").read().decode("utf-8", "ignore")
            assert _OUTLIER_TOKEN not in txt and "1990-07-15" not in txt


def test_triangulation_smoke_outlier_not_recoverable(tmp_path):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path), out_dir=out, thresholds=DEFAULTS)
    d = json.load(open(os.path.join(out, "dictionary.json")))
    td = d["files"][os.path.join("oura_ring", "TIME_oura_hr.csv")]["columns"]["timestamp"][
        "temporal_distribution"]
    # combining every disclosed distribution for the column must not narrow to 1 subject:
    # each disclosed aggregate describes >= k subjects / >= bin_min_count events.
    assert td["n_contributors"] >= DEFAULTS.k
    for hist_key in ("session_minutes", "gap_hours", "coverage_days"):
        for b in td[hist_key]:
            assert b["count"] >= DEFAULTS.bin_min_count
    # the outlier's lone 3am activity is coarsened+diluted, not a solo disclosing block:
    # its 00-04 block fraction stays a small share, never a 1-subject spike.
    assert td["diurnal_blocks"].get("00-04", 0.0) < 0.5
