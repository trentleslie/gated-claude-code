import json, os, pathlib
import pandas as pd
from gated_cs.profiler.build_dictionary import build, build_synthetic_from_dictionary
FX = pathlib.Path(__file__).parent.parent / "fixtures"


def _time_dir(tmp_path):
    base = tmp_path / "TIME"
    (base / "oura_ring").mkdir(parents=True)
    rows = [{"subject_id": f"S{s:03d}",
             "timestamp": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=d)
                           + pd.Timedelta(hours=8 + h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "hr": 60 + (h % 20)}
            for s in range(12) for d in range(5) for h in range(6)]
    pd.DataFrame(rows).to_csv(base / "oura_ring" / "TIME_oura_hr.csv", index=False)
    return str(base)

def test_build_emits_dictionary_and_samples(tmp_path):
    d = build(str(FX), str(tmp_path))
    assert (tmp_path / "dictionary.json").exists()
    assert (tmp_path / "dictionary.md").exists()
    assert (tmp_path / "synthetic_samples" / "simple.csv").exists()
    # every profiled file is present, both flat (files) and grouped (sources)
    assert {"simple.csv", "tabbed.tsv", "with_ids.csv"} <= set(d["files"])
    # fixtures sit directly under FX with no source subfolder -> grouped under ""
    assert set(d["sources"].keys()) == {""}
    assert {"simple.csv", "tabbed.tsv", "with_ids.csv"} <= set(d["sources"][""])
    assert (tmp_path / "run_manifest.json").exists()

def test_no_raw_values_leak(tmp_path):
    build(str(FX), str(tmp_path))
    text = (tmp_path / "dictionary.json").read_text()
    assert "user0@example.com" not in text   # a real identifier value
    assert '"min"' not in text and '"max"' not in text


def _hr_col(tmp_path):
    data_dir = _time_dir(tmp_path)
    out = tmp_path / "out"
    build(data_dir, str(out))
    d = json.loads((out / "dictionary.json").read_text())
    rel = os.path.join("oura_ring", "TIME_oura_hr.csv")
    return out, d, d["files"][rel]["columns"]["timestamp"]


def test_dictionary_serializes_format_and_distribution(tmp_path):
    out, d, ts = _hr_col(tmp_path)
    assert ts["format"]["template"] == "%Y-%m-%dT%H:%M:%SZ"
    td = ts["temporal_distribution"]
    assert "cadence" in td and "diurnal_blocks" in td and "coverage_days" in td


def test_markdown_shows_template_and_summary_leak_free(tmp_path):
    out, d, ts = _hr_col(tmp_path)
    md = (out / "dictionary.md").read_text()
    assert "%Y-%m-%dT%H:%M:%SZ" in md          # value-free template surfaced
    # no raw timestamp value, no per-subject id leaks into md
    assert "2025-01-01T08" not in md
    assert "S000" not in md and "S011" not in md


def test_dict_only_synthesis_reads_descriptors_no_raw(tmp_path):
    out, d, ts = _hr_col(tmp_path)
    import shutil
    shutil.rmtree(out / "synthetic_samples")
    n = build_synthetic_from_dictionary(str(out / "dictionary.json"), str(out))
    assert n == 1
    dest = out / "synthetic_samples" / "oura_ring" / "TIME_oura_hr.csv"
    assert dest.exists()
    syn = pd.read_csv(dest)
    # timestamps rendered in the captured ISO-Z format, not the old date-only path
    assert syn["timestamp"].astype(str).str.contains("T").all()
    assert syn["timestamp"].astype(str).str.endswith("Z").all()
