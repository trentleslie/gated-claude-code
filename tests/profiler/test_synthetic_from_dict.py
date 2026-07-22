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
