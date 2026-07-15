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

def test_non_csv_artifact_is_quarantined(tmp_path):
    body = ("import os\n"
            "open(os.path.join(os.environ['OUTPUT_DIR'],'raw.json'),'w').write('{\"ssn\":\"123-45-6789\"}')\n")
    r = run(_script(tmp_path, body), str(tmp_path/'data'), str(tmp_path/'out'),
            str(tmp_path/'audit.jsonl'), str(tmp_path/'queue'))
    assert r["status"] == "queued"
    import glob
    assert glob.glob(str(tmp_path/'out'/'**'/'*.json'), recursive=True) == []  # not left in out_dir
    assert glob.glob(str(tmp_path/'queue'/'*raw.json'))                        # quarantined instead

def test_zero_artifact_run_is_audited(tmp_path):
    from gated_cs.gate.audit import AuditLog
    r = run(_script(tmp_path, "x = 1\n"), str(tmp_path/'data'), str(tmp_path/'out'),
            str(tmp_path/'audit.jsonl'), str(tmp_path/'queue'))
    assert r["status"] == "released" and r["outputs"] == []
    assert any(e.get("verdict") == "run" for e in AuditLog(str(tmp_path/'audit.jsonl')).entries())

def test_flatten_collision_both_quarantined(tmp_path):
    # a/b.csv and a_b.csv previously flattened to the same queue name; both must survive
    import glob
    body = ("import os, pandas as pd\n"
            "d = os.environ['OUTPUT_DIR']\n"
            "os.makedirs(os.path.join(d, 'a'), exist_ok=True)\n"
            "pd.DataFrame({'x': range(100)}).to_csv(os.path.join(d, 'a', 'b.csv'), index=False)\n"
            "pd.DataFrame({'x': range(100)}).to_csv(os.path.join(d, 'a_b.csv'), index=False)\n")
    r = run(_script(tmp_path, body), str(tmp_path/'data'), str(tmp_path/'out'),
            str(tmp_path/'audit.jsonl'), str(tmp_path/'queue'))
    assert r["status"] == "queued"
    assert len(glob.glob(str(tmp_path/'queue'/'*'))) == 2   # neither overwrote the other

def test_identical_script_reruns_dont_overwrite_queue(tmp_path):
    import glob
    body = ("import os, pandas as pd\n"
            "pd.DataFrame({'x': range(100)}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    args = (str(tmp_path/'data'), str(tmp_path/'out'), str(tmp_path/'audit.jsonl'), str(tmp_path/'queue'))
    run(_script(tmp_path, body), *args)
    run(_script(tmp_path, body), *args)   # identical script, same artifact name, second run
    assert len(glob.glob(str(tmp_path/'queue'/'*'))) == 2   # one quarantined file per run
