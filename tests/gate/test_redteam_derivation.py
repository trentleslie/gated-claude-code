import json, os, pandas as pd
from gated_cs.gate.run_analysis import run

def _base(tmp_path):
    for n in ("data","store","out","q","res"): (tmp_path/n).mkdir()
    return (str(tmp_path/"data"), str(tmp_path/"store"), str(tmp_path/"out"),
            str(tmp_path/"q"), str(tmp_path/"res"), str(tmp_path/"a.jsonl"))

def test_rows_to_output_still_quarantined_in_derivation(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX","1")
    data,store,out,q,res,audit=_base(tmp_path); s=str(tmp_path/"d.py")
    open(s,"w").write(
        "import os,pandas as pd\n"
        "pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(5)],'v':range(5)})"
        ".to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        # a 100-row dump to OUTPUT_DIR must be quarantined by the gate
        "pd.DataFrame({'x':range(100)}).to_csv(os.path.join(os.environ['OUTPUT_DIR'],'dump.csv'),index=False)\n")
    r=run(s,data,out,audit,q,results_dir=res,layer_dir=str(tmp_path/"stg"),layer_name="L",derived_dir=store)
    assert r["status"]=="queued"                              # dump did NOT release
    assert os.listdir(res)==[] or all("dump" not in f for f in os.listdir(res))

def test_layer_dir_rows_persist_but_are_not_delivered(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX","1")
    data,store,out,q,res,audit=_base(tmp_path); s=str(tmp_path/"d.py")
    open(s,"w").write(
        "import os,pandas as pd\n"
        # write 500 raw-looking rows to the STORE (LAYER_DIR)
        "pd.DataFrame({'public_client_id':['SYNTH_%04d'%i for i in range(500)],'raw':range(500)})"
        ".to_csv(os.path.join(os.environ['LAYER_DIR'],'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n")
    run(s,data,out,audit,q,results_dir=res,layer_dir=str(tmp_path/"stg"),layer_name="L",derived_dir=store)
    # persisted in the store...
    assert os.path.exists(os.path.join(store,"L","MANIFEST.json"))
    # ...but NOTHING delivered to results/ (the only cs-gated-readable path)
    assert os.listdir(res)==[]

def test_child_cannot_forge_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("GATED_CS_NO_SANDBOX","1")
    data,store,out,q,res,audit=_base(tmp_path); s=str(tmp_path/"d.py")
    open(s,"w").write(
        "import os,pandas as pd\n"
        "d=os.environ['LAYER_DIR']\n"
        "pd.DataFrame({'public_client_id':['SYNTH_0001'],'v':[1]}).to_csv(os.path.join(d,'data.tsv.gz'),sep='\\t',index=False,compression='gzip')\n"
        "open(os.path.join(d,'MANIFEST.json'),'w').write('{\"forged\":true}')\n")
    run(s,data,out,audit,q,results_dir=res,layer_dir=str(tmp_path/"stg"),layer_name="L",derived_dir=store)
    man=json.loads(open(os.path.join(store,"L","MANIFEST.json")).read())
    assert "forged" not in man and man["name"]=="L"          # executor's manifest wins
