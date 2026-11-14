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

def test_add_layer_refuses_uuid_column_names_before_writing(tmp_path):
    import pytest
    from gated_cs.profiler.build_dictionary import PublishedUUIDError
    data = tmp_path/"data"; data.mkdir()
    pd.DataFrame({"public_client_id":["SYNTH_0001","SYNTH_0002"],"glucose":[90,95]}).to_csv(data/"chem.csv", index=False)
    out = tmp_path/"dict"; build(str(data), str(out))
    before = {p: (out/p).read_bytes() for p in ("dictionary.json", "dictionary.md")}
    staff = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    # a pivot whose column names are staff UUIDs
    layer = pd.DataFrame({"public_client_id":["SYNTH_0001","SYNTH_0002"], staff:[1.0,2.0]})
    with pytest.raises(PublishedUUIDError) as e:
        add_layer_to_dictionary(str(out/"dictionary.json"), str(out), "pivot", layer)
    assert staff not in str(e.value) and "nothing was written" in str(e.value)
    # nothing published: both dictionary files untouched, no sample written
    assert {p: (out/p).read_bytes() for p in before} == before
    assert not (out/"synthetic_samples"/"pivot.csv").exists()

def test_scan_fails_on_unreadable_sample_directory(tmp_path):
    import pytest
    from gated_cs.profiler.build_dictionary import _scan_samples
    if os.geteuid() == 0:
        pytest.skip("root reads any directory")
    locked = tmp_path/"synthetic_samples"/"old"; locked.mkdir(parents=True)
    (locked/"stale.csv").write_text("a\n1\n")
    locked.chmod(0)
    try:
        found = _scan_samples(str(tmp_path))
    finally:
        locked.chmod(0o700)
    assert found == {str(locked): ["synthetic_samples/old (unreadable directory, cannot be checked)"]}
