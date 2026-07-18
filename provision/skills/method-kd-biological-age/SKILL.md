---
name: method-kd-biological-age
description: Compute multi-omic biological age (Klemera-Doubal BA_E) and ΔAge (BA − CA) on gated Arivale from clinical labs, metabolomics, and/or proteomics — a verified reproduction of Earls 2019 (PMID 31724055; reproduced r(BA,CA)=0.78, MAE 5.44 yr). Use when an analysis needs a biological-age / ΔAge readout, compares predicted vs chronological age, or asks how much a condition (e.g. T2D) ages someone. Backed by analyses/_lib/kd.py + methods/kd-biological-age/provenance.json.
---

# method-kd-biological-age

Verified, citation-backed method. Canonical code: `analyses/_lib/kd.py` (+ `stats.cluster_ols`).
Entry point: `methods/kd-biological-age/method.py` → `biological_age(train_features, train_ca, test_features)`.
Provenance (paper, gate release hash, reproduced-vs-published): `methods/kd-biological-age/provenance.json`.

## When to apply (auto-invoke triggers)
- Estimating biological age or ΔAge from omics; predicted-vs-chronological-age comparisons;
  quantifying a disease/behaviour's effect on apparent age.

## How to apply
1. Build per-sex (and per-vendor for labs) baseline-trained matrices; standardize with train stats.
2. Call `biological_age(...)` (imports the verified `_lib.kd`). For a GATE submission, inline the
   `_lib` primitive source into the submitted script (the sandbox cannot import `_lib`).
3. Report aggregates only; cite via `provenance.json`.

## Guardrail (autonomy boundary)
Auto-invocation selects and constructs the method with verified code. It MUST NOT submit a real-data
gate run unattended — surface the plan to the human before any `submit-analysis`.
