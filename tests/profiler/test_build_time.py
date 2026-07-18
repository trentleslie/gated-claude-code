import os, json
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.build_dictionary import build

def _mk(tmp_path):
    base = tmp_path / "TIME"
    (base / "oura_ring").mkdir(parents=True)
    (base / "stelo_cgm" / "processed").mkdir(parents=True)
    (base / "stelo_cgm" / "processed" / ".ipynb_checkpoints").mkdir(parents=True)
    (base / "redcap_questionnaires" / "raw").mkdir(parents=True)
    # wearable file
    rows = [{"subject_id": f"S{s:02d}",
             "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(minutes=5 * i),
             "hr": 60 + (i % 30)} for s in range(10) for i in range(30)]
    pd.DataFrame(rows).to_csv(base / "oura_ring" / "TIME_oura_heartrate.csv", index=False)
    # checkpoint dupe that must be ignored
    pd.DataFrame(rows).to_csv(
        base / "stelo_cgm" / "processed" / ".ipynb_checkpoints" / "x-checkpoint.csv", index=False)
    # cgm
    pd.DataFrame(rows).to_csv(base / "stelo_cgm" / "processed" / "TIME_cgm_all_subjects.csv", index=False)
    # codebook
    pd.DataFrame({"field_name": ["q1", "q2"],
                  "question_text": ["How rested?", "How stressed?"]}
                 ).to_csv(base / "redcap_questionnaires" / "raw" / "TIME_redcap_questions.csv", index=False)
    return str(base)

def test_build_groups_by_source_skips_checkpoints_and_writes_manifest(tmp_path):
    data_dir = _mk(tmp_path)
    out = str(tmp_path / "out")
    d = build(data_dir, out_dir=out, thresholds=DEFAULTS)
    # 3 real files, no checkpoint
    assert set(d["sources"].keys()) == {"oura_ring", "stelo_cgm", "redcap_questionnaires"}
    assert len(d["files"]) == 3
    assert not any(".ipynb_checkpoints" in r for r in d["files"])
    # subject key + cohort surfaced
    hr = d["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]
    assert hr["subject_key"] == "subject_id" and hr["cohort_n"] == 10
    assert "temporal_coverage" in hr["columns"]["timestamp"]
    # codebook role + descriptive text surfaced in md
    md = open(os.path.join(out, "dictionary.md")).read()
    assert "How rested?" in md
    # artifacts written
    assert os.path.exists(os.path.join(out, "dictionary.json"))
    assert os.path.exists(os.path.join(out, "run_manifest.json"))
    assert os.path.exists(os.path.join(out, "synthetic_samples",
                                       "oura_ring", "TIME_oura_heartrate.csv"))
    manifest = json.load(open(os.path.join(out, "run_manifest.json")))
    assert manifest["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]["row_count"] == 300
    assert "sha256" in manifest["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]

def test_build_synthetic_samples_leak_nothing_real(tmp_path):
    data_dir = _mk(tmp_path)
    out = str(tmp_path / "out2")
    build(data_dir, out_dir=out, thresholds=DEFAULTS)
    synth = open(os.path.join(out, "synthetic_samples", "oura_ring", "TIME_oura_heartrate.csv")).read()
    # real subject ids look like S00..S09; synthetic id_pool uses SYNTH_ prefix
    assert "S00" not in synth and "SYNTH_" in synth
