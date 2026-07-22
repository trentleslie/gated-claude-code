import json, os, pandas as pd
from gated_cs.profiler.build_dictionary import build, add_layer_to_dictionary

def test_add_layer_merges_and_tags_derived(tmp_path):
    data = tmp_path/"data"; data.mkdir()
    pd.DataFrame({"public_client_id":["SYNTH_0001","SYNTH_0002"],"glucose":[90,95]}).to_csv(data/"chem.csv", index=False)
    out = tmp_path/"dict"; build(str(data), str(out))
    layer = pd.DataFrame({"public_client_id":["SYNTH_0001","SYNTH_0002"],"imp":[1.0,2.0]})
    add_layer_to_dictionary(str(out/"dictionary.json"), str(out), "metabolomics_imputed", layer)
    d = json.loads((out/"dictionary.json").read_text())
    assert "metabolomics_imputed" in d["files"]
    assert d["files"]["metabolomics_imputed"]["derived"] is True
    assert (out/"synthetic_samples"/"metabolomics_imputed.csv").exists()
    syn = pd.read_csv(out/"synthetic_samples"/"metabolomics_imputed.csv")
    assert syn["public_client_id"].str.startswith("SYNTH_").all()   # shared pool -> joinable
    # regression: _render_md iterates d["sources"]; the derived layer must be
    # registered there too, or it silently vanishes from the regenerated md.
    md = (out/"dictionary.md").read_text()
    assert "metabolomics_imputed" in md
    assert "imp" in md   # a non-sensitive column of the layer
