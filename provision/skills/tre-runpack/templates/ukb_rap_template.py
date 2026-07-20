#!/usr/bin/env python3
"""UKB-RAP run-pack template — RUN INSIDE the UK Biobank Research Analysis Platform.

Reproduces an Arivale discovery statistic on UK Biobank and exports ONLY aggregate
coefficients, per UK Biobank return rules. Fill every {{TOKEN}} before running.

Setup (RAP JupyterLab / Swiss-Army-Knife job):
  dx extract_dataset "{{DATASET_RECORD}}" --fields "{{FIELD_IDS_CSV}}" -o pheno.csv
  # Spark instance required if pulling >30 fields.
"""
import pandas as pd
import numpy as np  # noqa: F401  (available in RAP images; used by most {{MODEL}} fills)

PLATFORM = "ukb-rap"
DATASET_RECORD = "{{DATASET_RECORD}}"          # e.g. app12345_dataset
FIELD_IDS = "{{FIELD_IDS_CSV}}".split(",")     # UKB-PPP Olink / Nightingale NMR field ids
OUTCOME_FIELD = "{{OUTCOME_FIELD}}"            # e.g. chronological age field id
METRIC = "{{METRIC}}"                          # e.g. "beta_per_sd" / "cv_r2"
OUTPUT_CSV = "tre_aggregates.csv"
MIN_CELL = 5                                   # UKB return-rule floor; raise per DUA


def fit(pheno: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the transferred Arivale statistic.

    Fill {{MODEL}}: return one row per feature with columns feature, beta, se, n.
    """
    raise NotImplementedError("fill {{MODEL}} with the transferred method")


def main() -> None:
    pheno = pd.read_csv("pheno.csv")
    res = fit(pheno)
    res = res[res["n"] >= MIN_CELL].copy()
    res["metric"] = METRIC
    res["platform"] = PLATFORM
    res[["feature", "beta", "se", "n", "metric", "platform"]].to_csv(OUTPUT_CSV, index=False)
    print(f"wrote {OUTPUT_CSV}: {len(res)} features")


if __name__ == "__main__":
    main()
