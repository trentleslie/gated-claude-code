import importlib.util
from pathlib import Path
import pandas as pd

_p = Path(__file__).resolve().parents[2] / "provision" / "skills" / "tre-runpack" / "reconcile.py"
_spec = importlib.util.spec_from_file_location("reconcile", _p)
reconcile_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reconcile_mod)

def test_perfect_concordance():
    a = pd.DataFrame({"feature": ["m1", "m2", "m3"], "beta": [0.5, -0.3, 0.2]})
    t = pd.DataFrame({"feature": ["m1", "m2", "m3"], "beta": [0.4, -0.6, 0.1]})
    r = reconcile_mod.reconcile(a, t)
    assert r["shared_features"] == 3
    assert r["direction_concordance"] == 1.0
    assert r["effect_rank_spearman"] > 0.9

def test_partial_and_effect_column_alias():
    a = pd.DataFrame({"feature": ["m1", "m2", "m3", "m4"], "beta": [0.5, -0.3, 0.2, 0.9]})
    t = pd.DataFrame({"feature": ["m1", "m2", "m3"], "effect": [0.4, 0.6, 0.1]})  # m2 flips
    r = reconcile_mod.reconcile(a, t)
    assert r["shared_features"] == 3            # m4 not shared
    assert abs(r["direction_concordance"] - 2/3) < 1e-9

def test_no_overlap():
    a = pd.DataFrame({"feature": ["x"], "beta": [1.0]})
    t = pd.DataFrame({"feature": ["y"], "beta": [1.0]})
    r = reconcile_mod.reconcile(a, t)
    assert r["shared_features"] == 0
    assert r["direction_concordance"] is None
