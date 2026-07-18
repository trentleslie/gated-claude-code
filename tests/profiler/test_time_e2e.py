import os, json, glob
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.build_dictionary import build

def _mk(tmp_path):
    base = tmp_path / "TIME"
    (base / "oura_ring").mkdir(parents=True)
    (base / "redcap_demographics").mkdir(parents=True)
    rows = [{"subject_id": f"S{s:02d}",
             "timestamp": pd.Timestamp("2025-01-01") + pd.Timedelta(minutes=5 * i),
             "hr": 60 + (i % 30),
             "SECRET_NOTE": f"note_{s}_{i}"}      # near-unique free text -> must be suppressed
            for s in range(12) for i in range(40)]
    pd.DataFrame(rows).to_csv(base / "oura_ring" / "TIME_oura_heartrate.csv", index=False)
    demo = pd.DataFrame({"subject_id": [f"S{s:02d}" for s in range(12)],
                         "date_of_birth": ["1990-01-01"] * 12,
                         "sex": ["F"] * 6 + ["M"] * 6,
                         "rare_flag": ["common"] * 11 + ["UNIQUE_X"]})  # count<k -> suppressed
    demo.to_csv(base / "redcap_demographics" / "TIME_redcap_demographics.csv", index=False)
    return str(base)

def test_no_raw_values_and_kanon_hold(tmp_path):
    data_dir = _mk(tmp_path)
    out = str(tmp_path / "out")
    build(data_dir, out_dir=out, thresholds=DEFAULTS)

    dict_json = open(os.path.join(out, "dictionary.json")).read()
    all_synth = "".join(open(p).read() for p in
                        glob.glob(os.path.join(out, "synthetic_samples", "**", "*.csv"), recursive=True))
    blob = dict_json + all_synth

    # 1. free-text near-unique values never leak
    assert "SECRET_NOTE" in dict_json          # column name is fine
    assert "note_0_0" not in blob and "note_5_10" not in blob
    # 2. real subject ids never leak (SYNTH_ pool only)
    assert "S00" not in all_synth and "S11" not in all_synth
    # 3. exact DOB never leaks; date column suppressed
    assert "1990-01-01" not in blob
    # 4. rare category (<k) suppressed
    assert "UNIQUE_X" not in blob
    # 5. temporal coverage present but only month-granular
    d = json.load(open(os.path.join(out, "dictionary.json")))
    ts = d["files"][os.path.join("oura_ring", "TIME_oura_heartrate.csv")]["columns"]["timestamp"]
    assert ts["temporal_coverage"]["min_month"] == "2025-01"
    assert "2025-01-01" not in json.dumps(ts)   # no day/second granularity anywhere on the column
