"""Edge-case tests for persist_layer (TSV data files only, no parquet)."""
import json
import os

import pytest

from gated_cs.gate.derive import DerivationError, persist_layer


def _setup(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    store = tmp_path / "store"
    store.mkdir()
    script = tmp_path / "script.py"
    script.write_text("print('derive')\n")
    return stage, store, script


def _persist(stage, store, script, name="layer1"):
    return persist_layer(
        str(stage), str(store), name,
        script_path=str(script), data_dir="/data", derived_dir="/derived",
        params={"k": 1}, fit_quality={"r2": 0.5},
    )


def test_empty_matrix_raises(tmp_path):
    stage, store, script = _setup(tmp_path)
    (stage / "data.tsv").write_text("public_client_id\tx\n")
    with pytest.raises(DerivationError, match="empty"):
        _persist(stage, store, script)
    assert not (store / "layer1").exists()


def test_missing_data_file_raises(tmp_path):
    stage, store, script = _setup(tmp_path)
    (stage / "model.pkl").write_bytes(b"model")
    with pytest.raises(DerivationError, match="no data"):
        _persist(stage, store, script)
    assert not (store / "layer1").exists()


def test_model_files_moved_next_to_data(tmp_path):
    stage, store, script = _setup(tmp_path)
    (stage / "data.tsv").write_text("public_client_id\tx\nA\t1\nB\t2\n")
    (stage / "model.pkl").write_bytes(b"model-bytes")
    (stage / "model.json").write_text('{"coef": 1}')
    manifest = _persist(stage, store, script)
    dest = store / "layer1"
    assert (dest / "data.tsv").is_file()
    assert (dest / "model.pkl").read_bytes() == b"model-bytes"
    assert (dest / "model.json").read_text() == '{"coef": 1}'
    assert not os.path.exists(stage / "data.tsv")
    assert not os.path.exists(stage / "model.pkl")
    assert not os.path.exists(stage / "model.json")
    assert manifest["data_file"] == "data.tsv"


def test_manifest_n_persons_counts_unique_ids(tmp_path):
    stage, store, script = _setup(tmp_path)
    (stage / "data.tsv").write_text(
        "public_client_id\tx\nA\t1\nA\t2\nB\t3\nC\t4\nC\t5\n"
    )
    manifest = _persist(stage, store, script)
    on_disk = json.loads((store / "layer1" / "MANIFEST.json").read_text())
    assert on_disk["n_persons"] == 3
    assert on_disk["n_rows"] == 5
    assert manifest["n_persons"] == 3
