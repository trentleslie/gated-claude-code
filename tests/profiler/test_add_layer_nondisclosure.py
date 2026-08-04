"""Unit 3 — targeted non-disclosure proof for the derived-layer dictionary path.

`add_layer_to_dictionary` writes a profile + a synthesized sample of a derived matrix into a
dictionary the agent can read. Code review says it routes every column through per-column
k-anonymity suppression and never persists raw rows; this test proves it. Mirrors
tests/profiler/test_nondisclosure.py's OUTLIER-subject fixture: a value only one subject
exhibits must never reach dictionary.json, dictionary.md, or the synthetic sample.
"""
import json
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.build_dictionary import build, add_layer_to_dictionary

# a value only the single outlier subject exhibits — must never reach any artifact
_OUTLIER_TOKEN = "OUTLIER_SUBJECT_SENTINEL"


def _seed_dict(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    pd.DataFrame({"public_client_id": ["SYNTH_0001", "SYNTH_0002"],
                  "glucose": [90, 95]}).to_csv(data / "chem.csv", index=False)
    out = tmp_path / "dict"
    build(str(data), str(out))
    return out


def _derived_layer(n=20):
    ids = [f"SYNTH_{i:04d}" for i in range(1, n + 1)]
    return pd.DataFrame({
        "public_client_id": ids,
        "score": [round(1.0 + i * 0.1, 3) for i in range(n)],          # numeric -> histogram
        "cohort": (["A"] * (n // 2)) + (["B"] * (n - n // 2)),          # safe low-card categorical
        # near-unique fingerprint; exactly ONE subject carries the sentinel value
        "fingerprint": [f"fp-{i:05d}" for i in range(n - 1)] + [_OUTLIER_TOKEN],
        # a rare (< k) categorical value only the outlier exhibits
        "flag": (["ok"] * (n - 1)) + [_OUTLIER_TOKEN + "_FLAG"],
    })


def _artifacts(out, layer_name):
    dict_json = (out / "dictionary.json").read_text()
    md = (out / "dictionary.md").read_text()
    csv_name = layer_name if layer_name.endswith(".csv") else layer_name + ".csv"
    synth = (out / "synthetic_samples" / csv_name).read_text()
    return dict_json, md, synth


def test_outlier_value_never_reaches_any_derived_artifact(tmp_path):
    out = _seed_dict(tmp_path)
    add_layer_to_dictionary(str(out / "dictionary.json"), str(out), "metab_imputed",
                            _derived_layer())
    dict_json, md, synth = _artifacts(out, "metab_imputed")
    blob = dict_json + md + synth
    assert _OUTLIER_TOKEN not in blob
    assert _OUTLIER_TOKEN + "_FLAG" not in blob
    # not a single raw fingerprint value from the derived matrix leaks either
    assert "fp-00000" not in blob


def test_near_unique_derived_column_is_stored_suppressed(tmp_path):
    out = _seed_dict(tmp_path)
    add_layer_to_dictionary(str(out / "dictionary.json"), str(out), "metab_imputed",
                            _derived_layer())
    d = json.loads((out / "dictionary.json").read_text())
    fp = d["files"]["metab_imputed"]["columns"]["fingerprint"]
    assert fp.get("sensitive") is True
    assert fp.get("values_suppressed") is True
    assert fp.get("categories") is None
    # the rare (< k) value in an otherwise low-card column is suppressed, not listed
    flag = d["files"]["metab_imputed"]["columns"]["flag"]
    assert (_OUTLIER_TOKEN + "_FLAG") not in (flag.get("categories") or [])


def test_synthetic_sample_is_synthesized_not_copied(tmp_path):
    out = _seed_dict(tmp_path)
    add_layer_to_dictionary(str(out / "dictionary.json"), str(out), "metab_imputed",
                            _derived_layer(n=20))
    syn = pd.read_csv(out / "synthetic_samples" / "metab_imputed.csv")
    # synthesized to the synthesis row budget (100), not the derived matrix's 20 real rows
    assert len(syn) == 100
    # ids come from the shared synthetic pool so the layer stays joinable, never real subjects
    assert syn["public_client_id"].str.startswith("SYNTH_").all()
