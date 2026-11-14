import os, shutil
import pandas as pd
from gated_cs.profiler.build_dictionary import build, build_synthetic_from_dictionary


def _grouped_dict(tmp_path):
    """Build a real grouped dictionary whose file keys are NESTED (source/subdir/name.csv)."""
    base = tmp_path / "TIME"
    (base / "oura_ring").mkdir(parents=True)
    rows = [{"time_traveler_id": f"S{s:02d}", "hr": 60 + (i % 20)}
            for s in range(8) for i in range(10)]
    pd.DataFrame(rows).to_csv(base / "oura_ring" / "TIME_oura_heartrate.csv", index=False)
    out = tmp_path / "out"
    build(str(base), out_dir=str(out))
    return str(out)


def test_build_synthetic_from_grouped_dict_creates_nested_dirs(tmp_path):
    out = _grouped_dict(tmp_path)
    # regenerate synthetic from dictionary.json alone (the build-synthetic CLI path)
    shutil.rmtree(os.path.join(out, "synthetic_samples"))
    n = build_synthetic_from_dictionary(os.path.join(out, "dictionary.json"), out)

    dest = os.path.join(out, "synthetic_samples", "oura_ring", "TIME_oura_heartrate.csv")
    assert os.path.exists(dest), "nested synthetic dir must be created (no OSError)"
    assert n == 1
    # join key auto-detected -> synthetic remaps real ids to the SYNTH_ pool
    txt = open(dest).read()
    assert "SYNTH_" in txt and "S00" not in txt


def test_dictionary_only_synthesis_fails_closed_on_uuid_category(tmp_path):
    # an older dictionary (built before the per-value filter) must not republish its UUIDs
    import glob, json, pytest
    from gated_cs.profiler.build_dictionary import PublishedUUIDError
    out = _grouped_dict(tmp_path)
    shutil.rmtree(os.path.join(out, "synthetic_samples"))
    u = "3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b"
    dict_path = os.path.join(out, "dictionary.json")
    d = json.load(open(dict_path))
    name = os.path.join("oura_ring", "TIME_oura_heartrate.csv")
    d["files"][name]["columns"]["coach"] = {
        "dtype": "object", "n": 80, "pct_missing": 0.0, "cardinality": 2,
        "sensitive": False, "categories": ["unassigned", u]}
    json.dump(d, open(dict_path, "w"))
    dest = str(tmp_path / "regen")
    with pytest.raises(PublishedUUIDError) as e:
        build_synthetic_from_dictionary(dict_path, dest)
    assert name in str(e.value) and "categories" in str(e.value) and u not in str(e.value)
    written = [p for p in glob.glob(os.path.join(dest, "**", "*"), recursive=True) if os.path.isfile(p)]
    assert all(u not in open(p).read() for p in written)
