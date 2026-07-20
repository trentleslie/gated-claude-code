# All of Us Researcher Workbench (Terra) — execution model
_Checked 2026-07-18. Re-verify against support.researchallofus.org._

- **No row-level egress.** Analyze in-platform (Jupyter / RStudio / SAS). Attempting to download
  row-level data triggers an egress alert. **Summary data is downloadable under a size threshold.**
- **Tiers:** Registered + Controlled Tier (WGS, genotyping arrays, proteomics ~10k, unshifted dates).
- **Hard small-cell rule:** no exported/derivable participant count of **1–20**. Enforce every exported
  group `>= 21`, or coarsen/suppress. This is stricter than our gate's floor of 5.
- **Data access:** build a cohort + concept set, read via the Workbench dataset builder / `BigQuery`
  into a dataframe; resolve proteomics + phenotype concept ids at fill time.
- **Output contract:** write `tre_aggregates.csv` (`feature,beta,se,n,metric,platform`) with every
  `n >= MIN_CELL (=21)`, then download the (small) aggregate file from the workspace bucket.
