---
name: validate
description: Validate an Arivale-discovered signal (coefficients / effect sizes / associations) against an independent OPEN cohort whose data lives in the workspace. Open data is public (non-PHI), so it needs NO gate — read it directly and compare direction/magnitude/concordance. Use when the user says "/validate", or asks to check/replicate/validate an Arivale finding in an external open dataset.
---

# /validate — test an Arivale finding in an open external cohort

The mirror image of `/replicate`. `/replicate` reproduces a PUBLISHED method on the GATED Arivale data;
`/validate` takes an Arivale DISCOVERY (a released aggregate — coefficients, effect sizes, correlations)
and checks whether it holds in an INDEPENDENT, OPEN cohort.

**Architectural key:** open validation data is PUBLIC (not PHI), so it does **not** go through the gate.
It lives in the workspace under `~/analysis/validation/<dataset>/` and you read and analyze it
**directly** — no synthetic step, no `submit-analysis`, no disclosure gate. The gate is only ever for the
Arivale raw data. (You can also fetch a public dataset with plain network access from the workspace; only
the gate *sandbox* is network-isolated.)

## Input
- **`/validate <discovery-result> <open-dataset>`**
  - `<discovery-result>`: a released Arivale aggregate, e.g. `analyses/<slug>/outputs/*.csv` holding the
    signal to test (metabolite→taxon betas, effect sizes, correlations).
  - `<open-dataset>`: a folder under `~/analysis/validation/`, e.g. `borenstein/FRANZOSA_IBD_2019`, `gutsy`, `cmd`.

## Available open validation datasets (cache under `~/analysis/validation/`)
- **`borenstein/`** — 14 paired **fecal** microbiome + metabolome datasets (2,900 samples), `.tsv`.
  Source: `github.com/borenstein-lab/microbiome-metabolome-curated-data`. For microbiome↔metabolite links
  (cross-platform check: fecal metabolome vs Arivale's blood metabolome — an honest, harder test).
- **`gutsy/`** — GUTSY Atlas published associations: 546,819 species↔**plasma**-metabolite + 997
  diversity↔metabolite betas from 8,583 people (Dekkers 2022, *Nat Commun*, gutsyatlas.serve.scilifelab.se).
  The closest match to Arivale's *blood*-metabolome↔microbiome design — validate metabolite↔taxon/diversity betas.
- **`cmd/`** — curatedMetagenomicData exports (22k metagenomes + age/sex/BMI/disease metadata). For
  microbiome-aging / diversity-health signals (e.g. uniqueness vs age). Needs an R/Bioconductor export first.

If the named dataset folder is absent, fetch it (workspace has network for public downloads).

## Steps
1. **Load the discovery signal.** Read the Arivale released aggregate — which features, what direction and
   magnitude (e.g. "plasma metabolite X positively predicts genus Y, β=…, in Arivale").
2. **Load the open dataset directly** from `~/analysis/validation/<dataset>/` (plain read — no gate, no
   synthetic). Map features across cohorts honestly: metabolite identity (HMDB/KEGG, not raw platform IDs),
   taxon names (genus/species), units, and any platform/sample-type difference (fecal vs blood metabolome).
   Document every cross-cohort mapping as an adaptation.
3. **Recompute the same statistic** on the open cohort (or, for GUTSY, look up the published β for each
   shared pair). Compare, over the shared features:
   - **direction concordance** (sign agreement) — the primary criterion;
   - **effect-size rank correlation** (Spearman of Arivale β vs open-cohort β);
   - **replication rate** — how many Arivale hits are same-sign (and significant) in the open cohort.
4. **Report.** Write a concordance table to `analyses/<slug>/validation_vs_<dataset>.csv` and the headline
   into the README: "N of M Arivale signals replicated (same direction) in <dataset>; effect-size rank r=…".
   State non-replications and their likely cause (platform, cohort ascertainment, fecal-vs-blood metabolome).

## Principles
- Validation is **public-data analysis** — no gate, no synthetic surface, run it directly in the workspace.
- **Direction agreement > exact magnitude** across platforms; a partial replication with a stated reason is
  a real result, not a failure to bury.
- A finding that replicates in an independent open cohort is publication-grade; one that doesn't is a lesson.
- Keep the discovery/validation split clean: never tune the Arivale analysis to make the open cohort agree.
