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
    import pandas as pd
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'group':['a','b'],'count':[100,2]})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    r = _run(tmp_path, body)
    assert r["status"] == "released"
    released = pd.read_csv(r["outputs"][0])
    assert 2 not in released["count"].tolist()      # small cell (n<5) suppressed
    assert 100 in released["count"].tolist()        # large cell retained
    assert "b" not in released["group"].tolist()

def test_giant_frame_without_identifier_is_queued(tmp_path):
    # row-cap (>20 rows) must block on its own, even with an innocuous column name
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'value': range(100)})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'], 'r.csv'), index=False)\n")
    r = _run(tmp_path, body)
    assert r["status"] == "queued"

def test_small_per_person_table_without_count_is_queued(tmp_path):
    # residual risk 1: a small table of per-person quasi-identifiers with NO count column
    # must be quarantined for human review, not auto-released as a clean aggregate.
    body = ("import pandas as pd, os\n"
            "pd.DataFrame({'note':[f'free text {i}' for i in range(10)]})"
            ".to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'), index=False)\n")
    r = _run(tmp_path, body)
    assert r["status"] == "queued"
    # the audit records the per-person heuristic as the reason it was quarantined
    import json
    entries = [json.loads(l) for l in (tmp_path/'audit.jsonl').read_text().splitlines() if l.strip()]
    reasons = " ".join(e.get("reason", "") for e in entries)
    assert "per-person" in reasons.lower()

def test_grouping_by_uuid_column_with_padding_is_queued(tmp_path):
    # the script controls its own output: group by a UUID-valued column, keep under 5
    # groups and pad with placeholder labels so the "mostly UUID" column rule does not fire.
    # The gate's per-value check must quarantine it; nothing reaches the results directory.
    (tmp_path / "data").mkdir()
    u1, u2 = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b", "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    import pandas as pd
    pd.DataFrame({"coach": [u1] * 10 + [u2] * 10}).to_csv(tmp_path / "data" / "clients.csv", index=False)
    body = ("import pandas as pd, os\n"
            "d = pd.read_csv(os.path.join(os.environ['DATA_DIR'], 'clients.csv'))\n"
            "g = d.groupby('coach').size().reset_index(name='count')\n"
            "pad = pd.DataFrame({'coach': ['x', 'y'], 'count': [10, 10]})\n"
            "pd.concat([g, pad]).to_csv(os.path.join(os.environ['OUTPUT_DIR'], 'r.csv'), index=False)\n")
    s = tmp_path / "s.py"; s.write_text(body)
    r = run(str(s), str(tmp_path / 'data'), str(tmp_path / 'out'), str(tmp_path / 'audit.jsonl'),
            str(tmp_path / 'queue'), results_dir=str(tmp_path / 'results'))
    assert r["status"] == "queued"
    results = tmp_path / "results"
    released = [p for p in results.rglob("*") if p.is_file()] if results.exists() else []
    assert released == []
    assert u1 not in (tmp_path / 'audit.jsonl').read_text()
