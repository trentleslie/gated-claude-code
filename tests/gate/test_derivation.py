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

import json
from gated_cs.gate.derive import persist_layer, DerivationError

def _stage_matrix(d, ids=("SYNTH_0001","SYNTH_0002")):
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"public_client_id":list(ids),"score":[1.0,2.0]}).to_csv(d/"data.tsv.gz", sep="\t", index=False, compression="gzip")

def test_persist_layer_writes_manifest_and_moves(tmp_path):
    stage = tmp_path/"stage"; _stage_matrix(stage)
    store = tmp_path/"store"; store.mkdir()
    script = tmp_path/"s.py"; script.write_text("print(1)")
    m = persist_layer(str(stage), str(store), "layerX", script_path=str(script),
                      data_dir=str(tmp_path/"data"), derived_dir=None,
                      params={"seed":0}, fit_quality={"cv_r2":0.45})
    assert (store/"layerX"/"MANIFEST.json").exists()
    man = json.loads((store/"layerX"/"MANIFEST.json").read_text())
    assert man["name"]=="layerX" and man["fit_quality"]["cv_r2"]==0.45
    assert "script_hash" in man and "data_hash" in man and "created_utc" in man
    assert (store/"layerX"/"PROVENANCE.jsonl").exists()

def test_persist_layer_rejects_missing_join_key(tmp_path):
    stage = tmp_path/"stage"; stage.mkdir()
    pd.DataFrame({"nope":[1,2]}).to_csv(stage/"data.tsv.gz", sep="\t", index=False, compression="gzip")
    store = tmp_path/"store"; store.mkdir(); s = tmp_path/"s.py"; s.write_text("x")
    try:
        persist_layer(str(stage), str(store), "bad", script_path=str(s), data_dir="d",
                      derived_dir=None, params={}, fit_quality={})
        assert False, "should reject"
    except DerivationError:
        pass

def test_derivation_persists_layer_and_releases_quality(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX", "1")
    data = tmp_path/"data"; data.mkdir()
    store = tmp_path/"store"; store.mkdir()
    out = tmp_path/"out"; q = tmp_path/"q"; res = tmp_path/"res"; audit = tmp_path/"a.jsonl"
    script = str(tmp_path/"d.py")
    open(script,"w").write(
        "import os,pandas as pd\n"
        "df=pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(10)],'imp':[float(i) for i in range(10)]})\n"
        "df.to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        "pd.DataFrame({'metric':['cv_r2'],'value':[0.45]}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'quality.csv'),index=False)\n")
    r = run(script, str(data), str(out), str(audit), str(q), results_dir=str(res),
            layer_dir=str(tmp_path/"stage"), layer_name="imp_layer",
            derived_dir=str(store))
    assert r["status"] == "released"                       # quality aggregate released
    assert (store/"imp_layer"/"MANIFEST.json").exists()    # layer persisted
    import json
    verdicts = [json.loads(l)["verdict"] for l in open(audit)]
    assert "derivation" in verdicts

def test_derivation_without_store_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX", "1")
    data = tmp_path/"data"; data.mkdir()
    out = tmp_path/"out"; q = tmp_path/"q"; res = tmp_path/"res"; audit = tmp_path/"a.jsonl"
    layer_dir = tmp_path/"stage"
    script = str(tmp_path/"d.py")
    open(script,"w").write(
        "import os,pandas as pd\n"
        "df=pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(10)],'imp':[float(i) for i in range(10)]})\n"
        "df.to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        "pd.DataFrame({'metric':['cv_r2'],'value':[0.45]}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'quality.csv'),index=False)\n")
    # No derived_dir configured -- must fail closed, not fall back to persisting
    # the derived matrix next to the ephemeral staging dir.
    r = run(script, str(data), str(out), str(audit), str(q), results_dir=str(res),
            layer_dir=str(layer_dir), layer_name="imp_layer", derived_dir=None)

    # (a) nothing persisted to a fallback location: no MANIFEST.json anywhere
    # under the staging dir's parent or the staging dir itself.
    for root, _dirs, files in os.walk(tmp_path):
        assert "MANIFEST.json" not in files, f"unexpected MANIFEST.json under {root}"

    # (b) audit log records the rejection
    verdicts = [json.loads(l) for l in open(audit)]
    rejected = [v for v in verdicts if v.get("verdict") == "derivation_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "no derived store configured"

    # (c) the run did not crash -- the quality aggregate still released
    assert r["status"] == "released"

def test_derivation_autoprofiles_and_screens_sensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX", "1")
    data = tmp_path/"data"; data.mkdir()
    dictdir = tmp_path/"dict";
    from gated_cs.profiler.build_dictionary import build
    (data/"chem.csv").write_text("public_client_id,glucose\nSYNTH_0001,90\nSYNTH_0002,95\n")
    build(str(data), str(dictdir))
    store = tmp_path/"store"; store.mkdir()
    out=tmp_path/"o"; q=tmp_path/"q"; res=tmp_path/"r"; audit=tmp_path/"a.jsonl"
    script=str(tmp_path/"d.py")
    open(script,"w").write(
        "import os,pandas as pd\n"
        "df=pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(8)],"
        "'imp':[float(i) for i in range(8)],'birth_date':['1980-01-01']*8})\n"
        "df.to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        "pd.DataFrame({'metric':['cv_r2'],'value':[0.5]}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'q.csv'),index=False)\n")
    run(script,str(data),str(out),str(audit),str(q),results_dir=str(res),
        layer_dir=str(tmp_path/"stage"),layer_name="imp_layer",derived_dir=str(store),
        dict_path=str(dictdir/"dictionary.json"))
    import json; d=json.loads((dictdir/"dictionary.json").read_text())
    assert d["files"]["imp_layer"]["derived"] is True
    assert d["files"]["imp_layer"]["columns"]["birth_date"]["sensitive"] is True  # re-encoded date screened
