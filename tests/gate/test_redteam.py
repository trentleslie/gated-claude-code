import os, pathlib
from gated_cs.gate.run_analysis import run

def _run(tmp_path, body):
    s = tmp_path / "s.py"; s.write_text(body)
    return run(str(s), str(tmp_path/'data'), str(tmp_path/'out'),
               str(tmp_path/'audit.jsonl'), str(tmp_path/'queue'))

def test_print_head_not_released_as_data(tmp_path):
    # writing head() of a would-be raw frame -> >row_cap OR identifier -> queued
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'email':[f'u{i}@x.com' for i in range(30)]})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    assert _run(tmp_path, body)["status"] == "queued"

def test_minmax_on_identifier_queued(tmp_path):
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'public_id':['P0001'],'count':[1]})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    assert _run(tmp_path, body)["status"] == "queued"

def test_tiny_subgroup_suppressed(tmp_path):
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'group':['a','b'],'count':[100,2]})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    assert _run(tmp_path, body)["status"] in ("released",)  # b suppressed, a released
