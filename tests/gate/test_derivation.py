import os, pandas as pd
from gated_cs.gate.run_analysis import run

def _write(p, s): open(p, "w").write(s); return p

def test_analysis_can_read_derived_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX", "1")
    data = tmp_path/"data"; data.mkdir()
    derived = tmp_path/"derived"; derived.mkdir()
    (derived/"layerX").mkdir()
    pd.DataFrame({"public_client_id":["SYNTH_0001"],"score":[1.0]}).to_csv(derived/"layerX"/"data.csv", index=False)
    out = tmp_path/"out"; q = tmp_path/"q"; res = tmp_path/"res"; audit = tmp_path/"a.jsonl"
    script = _write(str(tmp_path/"s.py"),
        "import os,glob,pandas as pd\n"
        "p=glob.glob(os.path.join(os.environ['DERIVED_DIR'],'layerX','data.*'))[0]\n"
        "n=len(pd.read_csv(p))\n"
        "pd.DataFrame({'metric':['rows'],'value':[n]}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'r.csv'),index=False)\n")
    r = run(script, str(data), str(out), str(audit), str(q), results_dir=str(res), derived_dir=str(derived))
    assert r["status"] == "released"
