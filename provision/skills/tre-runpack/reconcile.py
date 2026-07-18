#!/usr/bin/env python3
"""Reconcile an Arivale discovery aggregate against a TRE-returned aggregate.

Both inputs share a `feature` column and a signed effect column (`beta` or `effect`).
Public-data / returned-aggregate analysis only — never touches the gate.
"""
from __future__ import annotations
import sys
import pandas as pd

_EFFECT_COLS = ("beta", "effect")


def _effect_col(df: pd.DataFrame) -> str:
    for c in _EFFECT_COLS:
        if c in df.columns:
            return c
    raise ValueError(f"no effect column {_EFFECT_COLS} in {list(df.columns)}")


def reconcile(arivale: pd.DataFrame, tre: pd.DataFrame) -> dict:
    ac, tc = _effect_col(arivale), _effect_col(tre)
    merged = arivale[["feature", ac]].rename(columns={ac: "a"}).merge(
        tre[["feature", tc]].rename(columns={tc: "t"}), on="feature"
    )
    n = len(merged)
    if n == 0:
        return {"shared_features": 0, "direction_concordance": None,
                "effect_rank_spearman": None, "replication_rate": None}
    same_sign = ((merged["a"] > 0) & (merged["t"] > 0)) | ((merged["a"] < 0) & (merged["t"] < 0))
    concordance = float(same_sign.mean())
    rank_r = float(merged["a"].corr(merged["t"], method="spearman")) if n >= 2 else None
    return {
        "shared_features": int(n),
        "direction_concordance": concordance,
        "effect_rank_spearman": rank_r,
        "replication_rate": concordance,
    }


def main() -> None:
    a, t = pd.read_csv(sys.argv[1]), pd.read_csv(sys.argv[2])
    for k, v in reconcile(a, t).items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
