import pathlib
from gated_cs.gate.run_analysis import run

def _script(tmp_path, body):
    p = tmp_path / "s.py"; p.write_text(body); return str(p)

def test_clean_aggregate_released(tmp_path):
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'group':['a','b'],'count':[50,60]})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    r = run(_script(tmp_path, body), str(tmp_path/'data'), str(tmp_path/'out'),
            str(tmp_path/'audit.jsonl'), str(tmp_path/'queue'))
    assert r["status"] == "released" and r["outputs"]

def test_row_dump_queued(tmp_path):
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'x':range(100)})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    r = run(_script(tmp_path, body), str(tmp_path/'data'), str(tmp_path/'out'),
            str(tmp_path/'audit.jsonl'), str(tmp_path/'queue'))
    assert r["status"] == "queued"
    assert list(pathlib.Path(str(tmp_path/'queue')).glob("*.csv"))
