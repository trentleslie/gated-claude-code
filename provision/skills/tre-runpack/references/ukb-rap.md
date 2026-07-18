# UK Biobank Research Analysis Platform (UKB-RAP / DNAnexus) — execution model
_Checked 2026-07-18. RAP execution models drift; re-verify against dnanexus.gitbook.io/uk-biobank-rap._

- **No data download.** All work happens inside the RAP; only results (small aggregate files) leave,
  under UK Biobank return-of-results rules.
- **CLI:** `dx-toolkit` (`dx login`, `dx run`, `dx upload/download`). Run scripts via a JupyterLab app,
  RStudio, or the Swiss-Army-Knife app; WDL/Nextflow for reproducible workflows.
- **Tabular phenotype data** is dispensed as a Parquet **dataset record** in the project. Extract fields:
  `dx extract_dataset "<app####_dataset>" --fields "<f1>,<f2>,..." -o pheno.csv`. Use a **Spark** instance
  if pulling **>30 fields**.
- **Relevant assays:** UKB-PPP Olink (proteomics, ~2,900→5,400 proteins) and Nightingale NMR metabolomics
  are bulk/field-indexed — resolve exact field ids in the RAP data dictionary at fill time.
- **Output contract:** compute the statistic, keep only aggregate coefficients, write
  `tre_aggregates.csv` (`feature,beta,se,n,metric,platform`) with every group `n ≥ MIN_CELL` (floor 5;
  raise per your DUA), then `dx upload` / download from the project.
