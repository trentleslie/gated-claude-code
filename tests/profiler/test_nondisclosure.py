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
import pytest
from gated_cs.config import DEFAULTS
from gated_cs.profiler.build_dictionary import build

# a value only the single outlier subject exhibits — must never reach any artifact
_OUTLIER_TOKEN = "OUTLIER_SUBJECT"
_OUTLIER_SUBSECOND = ".987654"


# every control must hold for parquet sources too: their synthetic samples are written as
# parquet, which a raw byte scan can't reliably read (compressed, dictionary-encoded)
@pytest.fixture(params=["csv", "parquet"])
def fmt(request):
    return request.param


def _write(df, path, fmt):
    if fmt == "parquet":
        df.to_parquet(os.path.splitext(path)[0] + ".parquet", index=False)
    else:
        df.to_csv(path, index=False)


def _rel(*parts, fmt):
    return os.path.splitext(os.path.join(*parts))[0] + "." + fmt


def _text(path):
    # decoded content of a synthetic/artifact file, whatever its format
    if path.endswith(".parquet"):
        return pd.read_parquet(path).astype(str).to_csv(index=False)
    return open(path, "rb").read().decode("utf-8", "ignore")


def _mk_time(tmp_path, fmt="csv"):
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
    _write(pd.DataFrame(rows), base / "oura_ring" / "TIME_oura_hr.csv", fmt)

    # demographics: DOB (birth quasi-identifier) + a single-event enroll date
    demo = pd.DataFrame({
        "subject_id": [f"S{s:03d}" for s in range(12)],
        "date_of_birth": ["1990-07-15"] * 12,
        "enroll_date": [f"2024-1{(s % 2)+1}-0{(s % 9)+1}" for s in range(12)],
        "sex": ["F"] * 6 + ["M"] * 6,
    })
    _write(demo, base / "redcap" / "TIME_demographics.csv", fmt)
    return str(base)


def _artifacts(out):
    dict_json = open(os.path.join(out, "dictionary.json")).read()
    md = open(os.path.join(out, "dictionary.md")).read()
    synth = "".join(_text(p) for p in
                    glob.glob(os.path.join(out, "synthetic_samples", "**", "*"), recursive=True)
                    if os.path.isfile(p))
    return dict_json, md, synth


def test_leak_free_across_all_three_artifacts(tmp_path, fmt):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path, fmt), out_dir=out, thresholds=DEFAULTS)
    dict_json, md, synth = _artifacts(out)
    blob = dict_json + md + synth
    # no real subject ids
    assert _OUTLIER_TOKEN not in blob
    assert "S000" not in blob and "M000" not in blob
    # no raw birth date / birth month
    assert "1990-07-15" not in blob and "1990-07" not in blob


def test_below_k_minority_format_never_disclosed(tmp_path, fmt):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path, fmt), out_dir=out, thresholds=DEFAULTS)
    dict_json, md, synth = _artifacts(out)
    blob = dict_json + md + synth
    d = json.load(open(os.path.join(out, "dictionary.json")))
    ts = d["files"][_rel("oura_ring", "TIME_oura_hr.csv", fmt=fmt)]["columns"]["timestamp"]
    templates = [ts["format"]["template"]] + [m["template"] for m in ts["format"].get("minority", [])]
    # the < k subsecond format is neither in the descriptor nor rendered anywhere
    assert not any(".%f" in t for t in templates)
    assert _OUTLIER_SUBSECOND not in blob
    assert not re.search(r"\.\d{6}", synth)


def test_below_k_subgroup_distribution_suppressed(tmp_path, fmt):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path, fmt), out_dir=out, thresholds=DEFAULTS)
    d = json.load(open(os.path.join(out, "dictionary.json")))
    cols = d["files"][_rel("redcap", "TIME_demographics.csv", fmt=fmt)]["columns"]
    # DOB is a birth quasi-identifier -> no temporal facets at all
    assert "temporal_coverage" not in cols["date_of_birth"]
    assert "temporal_distribution" not in cols["date_of_birth"]
    # single-event enroll date -> no distribution captured (R16)
    assert "temporal_distribution" not in cols["enroll_date"]


def test_per_subject_intermediates_never_persist(tmp_path, fmt):
    out = str(tmp_path / "out")
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        build(_mk_time(tmp_path, fmt), out_dir=out, thresholds=DEFAULTS)
    logged = buf_out.getvalue() + buf_err.getvalue()
    # nothing per-subject printed/logged during the build
    assert _OUTLIER_TOKEN not in logged
    assert "S000" not in logged and "1990-07-15" not in logged
    # no stray intermediate file under out_dir carries a real subject id / raw stamp
    expected_top = {"dictionary.json", "dictionary.md", "run_manifest.json", "synthetic_samples"}
    assert set(os.listdir(out)) <= expected_top, "unexpected intermediate written to out_dir"
    for p in glob.glob(os.path.join(out, "**", "*"), recursive=True):
        if os.path.isfile(p):
            txt = _text(p)
            assert _OUTLIER_TOKEN not in txt and "1990-07-15" not in txt


def test_triangulation_smoke_outlier_not_recoverable(tmp_path, fmt):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path, fmt), out_dir=out, thresholds=DEFAULTS)
    d = json.load(open(os.path.join(out, "dictionary.json")))
    td = d["files"][_rel("oura_ring", "TIME_oura_hr.csv", fmt=fmt)]["columns"]["timestamp"][
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


# --- UUID-shaped values are never published (pre-rebuild hardening R1/R4) ---
import uuid
from gated_cs.profiler.sensitivity import UUID_TOKEN
from gated_cs.profiler.build_dictionary import PublishedUUIDError

# deterministic stand-ins for real staff UUIDs (the Arivale `coach` column)
_STAFF = [str(uuid.UUID(int=(0xC0AC << 108) + i * 0x10000000000000001 + 3)) for i in range(10)]
_CLIENTS = os.path.join("crm", "clients.csv")


def _mk_coach(tmp_path, fmt, coach):
    base = tmp_path / "ARV"
    (base / "crm").mkdir(parents=True)
    df = pd.DataFrame({"public_client_id": [f"C{i:04d}" for i in range(len(coach))],
                       "coach": coach,
                       "tier": ["gold", "silver"] * (len(coach) // 2)})
    _write(df, base / "crm" / "clients.csv", fmt)
    return str(base)


def _coach_pure():          # every value a UUID, each on 10 rows
    return _STAFF * 10

def _coach_mixed():         # 60% placeholder, 8 UUIDs on 5 rows each, interleaved
    out, n = [], 0
    for i in range(100):
        if i % 5 < 3:
            out.append("unassigned")
        else:
            out.append(_STAFF[n % 8]); n += 1
    return out

def _coach_late():          # no UUID in the first 200 rows (the column rule's sample)
    return ["unassigned"] * 200 + _STAFF * 10


def _assert_no_uuid(out, literals=_STAFF):
    dict_json, md, synth = _artifacts(out)
    for surface, text in (("dictionary.json", dict_json), ("dictionary.md", md),
                          ("synthetic_samples", synth)):
        assert not UUID_TOKEN.search(text), f"UUID-shaped value published in {surface}"
        for u in literals:
            assert u not in text and u.replace("-", "") not in text, surface


def test_pure_uuid_column_never_published(tmp_path, fmt):
    out = str(tmp_path / "out")
    d = build(_mk_coach(tmp_path, fmt, _coach_pure()), out_dir=out, thresholds=DEFAULTS)
    _assert_no_uuid(out)
    coach = d["files"][_rel(_CLIENTS, fmt=fmt)]["columns"]["coach"]
    assert coach["sensitive"] is True and coach["categories"] is None


def test_mixed_uuid_column_publishes_placeholder_only(tmp_path, fmt):
    out = str(tmp_path / "out")
    d = build(_mk_coach(tmp_path, fmt, _coach_mixed()), out_dir=out, thresholds=DEFAULTS)
    _assert_no_uuid(out)
    coach = d["files"][_rel(_CLIENTS, fmt=fmt)]["columns"]["coach"]
    assert coach["sensitive"] is False          # below the column bar: the per-value filter did it
    assert coach["categories"] == ["unassigned"]
    assert coach["uuid_categories_withheld"] == 8   # distinct UUIDs that met k


def test_uuids_after_sampled_rows_never_published(tmp_path, fmt):
    out = str(tmp_path / "out")
    d = build(_mk_coach(tmp_path, fmt, _coach_late()), out_dir=out, thresholds=DEFAULTS)
    _assert_no_uuid(out)
    coach = d["files"][_rel(_CLIENTS, fmt=fmt)]["columns"]["coach"]
    assert coach["categories"] == ["unassigned"]
    assert coach["uuid_categories_withheld"] == 10


def test_codebook_text_omits_uuid_cells(tmp_path, fmt):
    base = tmp_path / "ARV"
    (base / "redcap" / "raw").mkdir(parents=True)
    _write(pd.DataFrame({"field_name": ["q1", "q2", "q3"],
                         "question_text": ["How rested?", "owner " + _STAFF[0], "How stressed?"]}),
           base / "redcap" / "raw" / "ARV_questions.csv", fmt)
    out = str(tmp_path / "out")
    d = build(str(base), out_dir=out, thresholds=DEFAULTS)
    assert d["files"][_rel("redcap", "raw", "ARV_questions.csv", fmt=fmt)]["role"] == "codebook"
    _assert_no_uuid(out)
    md = open(os.path.join(out, "dictionary.md")).read()
    assert "How rested?" in md and "How stressed?" in md
    assert "1 UUID-shaped withheld" in md


def _assert_build_fails_closed(data_dir, out, *named):
    with pytest.raises(PublishedUUIDError) as e:
        build(data_dir, out_dir=out, thresholds=DEFAULTS)
    msg = str(e.value)
    for token in named:
        assert token in msg, msg
    assert not UUID_TOKEN.search(msg)           # the message names the place, not the value
    # nothing this build wrote stays behind for the analyst to read
    assert not os.path.exists(os.path.join(out, "dictionary.json"))
    assert not os.path.exists(os.path.join(out, "dictionary.md"))
    left = [p for p in glob.glob(os.path.join(out, "synthetic_samples", "**", "*"), recursive=True)
            if os.path.isfile(p)]
    assert left == []


def test_uuid_in_comment_line_fails_the_build(tmp_path):
    base = tmp_path / "ARV"
    (base / "crm").mkdir(parents=True)
    with open(base / "crm" / "clients.csv", "w") as f:
        f.write(f"# exported by {_STAFF[0]}\n")
        pd.DataFrame({"public_client_id": [f"C{i:03d}" for i in range(20)],
                      "tier": ["gold", "silver"] * 10}).to_csv(f, index=False)
    _assert_build_fails_closed(str(base), str(tmp_path / "out"), _CLIENTS, "file_metadata")


def test_uuid_as_column_name_fails_the_build(tmp_path, fmt):
    base = tmp_path / "ARV"
    (base / "crm").mkdir(parents=True)
    _write(pd.DataFrame({"public_client_id": [f"C{i:03d}" for i in range(20)],
                         _STAFF[0]: [1.0, 2.0] * 10}), base / "crm" / "clients.csv", fmt)
    _assert_build_fails_closed(str(base), str(tmp_path / "out"), _rel(_CLIENTS, fmt=fmt), "columns")


def test_uuid_in_file_name_fails_the_build(tmp_path):
    base = tmp_path / "ARV"
    (base / "crm").mkdir(parents=True)
    pd.DataFrame({"public_client_id": [f"C{i:03d}" for i in range(20)],
                  "tier": ["gold", "silver"] * 10}).to_csv(base / "crm" / f"{_STAFF[0]}.csv", index=False)
    _assert_build_fails_closed(str(base), str(tmp_path / "out"), "files")


def test_build_without_uuids_passes_scan_despite_manifest_digests(tmp_path, fmt):
    out = str(tmp_path / "out")
    build(_mk_time(tmp_path, fmt), out_dir=out, thresholds=DEFAULTS)
    manifest = open(os.path.join(out, "run_manifest.json")).read()
    assert re.search(r"[0-9a-f]{64}", manifest)      # SHA-256 input hashes are present ...
    assert not UUID_TOKEN.search(manifest)           # ... and are not UUID-shaped
