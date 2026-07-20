---
name: replicate
description: Reproduce a published study's method and target result on the gated Arivale data from the paper's PDF — extract the method, map it to Arivale's tables, recreate it through the gate, and compare to the paper's reported number. Use when the user says "/replicate <paper.pdf>", or asks to reproduce/replicate/recreate a published result or method on Arivale.
---

# /replicate — reproduce a published method on gated Arivale data

Given a publication PDF, recreate its method and check whether you hit its reported number, using the
gated pipeline. You (cs-gated) never read raw data — you develop against synthetic samples and submit
through `submit-analysis`; the gate runs your script on the real data and returns only disclosure-safe
aggregates.

Why this matters: reproducing a **published Arivale result through the gate, without the model ever
seeing a raw row**, is the strongest validation of the whole approach — it shows the pipeline yields
publication-grade, externally-checkable science, not just plausible-looking output. Faithfulness to the
method and honesty about every deviation matter more than hitting the number exactly.

## Input
- **`/replicate <path-to.pdf>`** — the paper. Put it somewhere you can read it, e.g. `~/analysis/papers/`.
- Optional second argument: which specific result to target if the paper reports several.

## Steps

1. **Read the paper.** Use the Read tool on the PDF (it reads PDFs natively, including figures/tables).
   Extract a short **replication spec**:
   - **Target result(s):** the exact quantitative claim to reproduce (e.g. "45% of α-diversity variance
     explained by 40 plasma metabolites"), with the paper's sample sizes and cohort definition.
   - **Method:** data layers used; preprocessing (transforms, filtering, which draw/visit, fasting);
     feature selection; the model or statistic; the exact metric and how it was evaluated (e.g.
     cross-validated R², AUC, correlation, effect size).
   Write this spec into `analyses/<NN-slug>/README.md` up front, with the full citation (authors, year,
   journal, PMID/DOI).

2. **Map to Arivale.** Read `dictionary.md` / `dictionary.json` for the exact tables and columns the
   method needs (column names, join key `public_client_id`, the real-file read pattern
   `pd.read_csv(path, sep="\t", skiprows=13, low_memory=False)`). Record honestly:
   - any data layer the paper used that Arivale lacks;
   - any platform/panel difference forcing an adaptation (e.g. NMR vs Metabolon, Olink vs Arivale
     proteomics, 16S vs shotgun) — analyte columns are keyed by ID with names in the `*_metadata` table,
     so resolve named features at run time via that map;
   - the sample-size difference vs the paper.
   Every forced change is documented as an **adaptation**, never a silent deviation.

3. **Build the analysis** in `analyses/<NN-slug>/<slug>.py`, following the workspace `CLAUDE.md`
   convention: read `DATA_DIR`, reproduce the method, and write **slug-prefixed** aggregate outputs — the
   reproduced metric plus the supporting tables a reader needs. Keep outputs gate-safe:
   - aggregates only, every group n ≥ 5;
   - **wide-format** (features as columns, groups as rows) so multi-feature tables stay under the gate's
     row cap (the gate caps rows, not columns);
   - never per-person rows or identifier columns.
   The scientific stack (`scikit-learn`, `scipy`, `statsmodels`, `numpy`, `pandas`) is available in the
   gate venv, so real models (elastic-net, regressions, cross-validation, proper stats) are fine.

4. **Develop against synthetic, then submit.** Test with the gate venv python and synthetic data:
   `DATA_DIR=synthetic_samples OUTPUT_DIR=/tmp/rep /opt/gated-cs/bin/python3 analyses/<NN-slug>/<slug>.py`
   — this validates the plumbing (the synthetic surface won't reproduce the real number; the real result
   comes from the gate). Then `submit-analysis analyses/<NN-slug>/<slug>.py` and iterate on any scrubbed
   gate errors.

5. **Collect + compare.** Copy this run's released files out of the flat inbox into the folder's
   `outputs/`, filtering by **this run's own hash prefix** (not just `*<slug>*`) so you don't pick up
   other runs. Then record in the README the headline: **reproduced value vs published value**, with an
   honest interpretation of any gap (cohort subset, platform adaptation, method difference, sample size).
   The comparison IS the deliverable.

6. **Optional figure:** `/jupyter analyses/<NN-slug>/<slug>.py` to render the reproduced result as a
   publication figure a human can run in JupyterLab.

## Principles
- Reproduce faithfully; document every deviation the data forces, as an adaptation.
- Report reproduced-vs-published honestly — a near-miss with a clear, stated reason is a good result; a
  suspiciously exact match deserves scrutiny, not celebration.
- Gate ethic: aggregates only. If the paper reports individual-level predictions, report the
  cross-validated metric (R²/AUC/correlation), never per-person outputs.
