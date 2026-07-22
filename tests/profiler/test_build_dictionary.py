import json, pathlib
from gated_cs.profiler.build_dictionary import build
FX = pathlib.Path(__file__).parent.parent / "fixtures"

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
