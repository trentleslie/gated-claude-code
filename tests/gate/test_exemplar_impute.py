import csv
import math
import os
import subprocess
import sys

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO_ROOT, "docs", "examples", "impute-metabolomics.py")
VENV_PYTHON = os.path.join(REPO_ROOT, ".venv", "bin", "python")


def _write_fixture(path, n_rows=40, n_feats=12, missing_frac=0.15, seed=0):
    rng = np.random.default_rng(seed)
    feats = [f"met_{i:03d}" for i in range(n_feats)]
    data = rng.normal(loc=100.0, scale=15.0, size=(n_rows, n_feats))
    missing = rng.random(data.shape) < missing_frac
    data[missing] = np.nan

    with open(path, "w", newline="") as fh:
        for i in range(13):
            fh.write(f"# comment line {i}\n")
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["public_client_id"] + feats)
        for i in range(n_rows):
            row = [f"SYNTH_{i:04d}"]
            for v in data[i]:
                row.append("" if math.isnan(v) else f"{v:.4f}")
            writer.writerow(row)


def test_exemplar_impute_produces_layer_and_finite_quality(tmp_path):
    data_dir = tmp_path / "data"
    layer_dir = tmp_path / "layer"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    layer_dir.mkdir()
    output_dir.mkdir()

    _write_fixture(data_dir / "metabolomics_corrected.tsv")

    env = dict(os.environ)
    env["DATA_DIR"] = str(data_dir)
    env["LAYER_DIR"] = str(layer_dir)
    env["OUTPUT_DIR"] = str(output_dir)

    result = subprocess.run(
        [VENV_PYTHON, SCRIPT],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    layer_file = layer_dir / "data.tsv.gz"
    assert layer_file.exists()

    quality_files = list(output_dir.glob("*quality.csv"))
    assert len(quality_files) == 1

    import pandas as pd

    quality = pd.read_csv(quality_files[0])
    cv_r2 = float(quality.loc[quality["metric"] == "cv_r2", "value"].iloc[0])
    assert math.isfinite(cv_r2)

    layer = pd.read_csv(layer_file, sep="\t", compression="gzip")
    assert "public_client_id" in layer.columns
    assert len(layer) == 40
    assert not layer.drop(columns=["public_client_id"]).isna().any().any()
