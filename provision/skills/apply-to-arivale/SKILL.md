---
name: apply-to-arivale
description: Transfer a frontier paper's METHOD to the gated Arivale data to produce a NEW result (not reproduce the paper's own number), deliberately adding Arivale-native tweaks/extensions that raise publication value, then route external validation — including non-exportable TREs. Use when the user says "/apply-to-arivale <paper.pdf>", or asks to apply/adapt a published method to Arivale and validate it.
---

# /apply-to-arivale — transfer a method to Arivale and validate it

The generative counterpart to `/replicate`. `/replicate` reproduces a paper's OWN number on Arivale;
`/apply-to-arivale` takes the paper's METHOD and produces a NEW Arivale finding, adding extensions that
exploit Arivale's moat over the (usually cross-sectional) source cohort — then validates it externally.
You (`cs-gated`) never read raw rows: develop against `synthetic_samples/`, submit through the gate,
release only aggregates.

## Input
- `/apply-to-arivale <paper.pdf> [--target <claim>] [--extension <angle>...] [--tre ukb-rap|all-of-us|both|none]`
- The paper is a staged frontier method source under `~/analysis/papers/` (see `papers_manifest.csv`).

## Pipeline
- **S0 — Application spec.** Read the PDF. Write `analyses/<NN-slug>/README.md`: the METHOD (layers,
  preprocessing, model, metric) AND the novel Arivale question it unlocks (the literature gap). Full
  citation from the manifest.
- **S1 — Map to Arivale.** From `dictionary.md`/`dictionary.json`, resolve tables/columns, join key
  `public_client_id`, real-file read (`sep="\t", skiprows=13`). Record every platform gap (NMR vs
  Metabolon, Olink panels, 16S vs shotgun; names via `*_metadata`) as a **forced adaptation**.
- **S2 — Value-add extensions.** Choose from the catalog below; tag each with the value it adds and the
  **wave/grade** it can reach. **Stop for a human pick before any gate spend.**
- **S3 — Build + gate-run.** `analyses/<NN-slug>/<slug>.py`; slug-prefix wide-format aggregate outputs
  (every group n >= 5, no identifiers); test on `synthetic_samples/`, then `submit-analysis`. Reuse
  `analyses/_lib/` and existing `methods/` modules — for aging-clock papers, build the clock with the
  verified **method-kd-biological-age** module, then apply the extensions on top.
- **S4 — Validation.** Downloadable open cohort -> `/validate`. Non-exportable TRE (`--tre`) ->
  `/tre-runpack <released-aggregate> <platform>`; the human runs the pack in the TRE and returns a
  `tre_aggregates.csv`; reconcile with `tre-runpack/reconcile.py` (direction concordance, effect-size
  rank correlation, replication rate).
- **S5 — Synthesize + grade.** README headline = Arivale discovery (with extensions) + external
  concordance + per-claim grade. **Optional:** promote a proven method to `methods/<name>/` with
  `provenance.json`.

## Publication-value extension catalog
1. **Longitudinal trajectory** — within-person change across repeated draws.
2. **Intervention pre/post response** — modifiability under the Arivale coaching arm.
3. **Cross-platform transfer** — Metabolon vs NMR, Olink panel differences (a harder, honest test).
4. **Multi-omic joint modeling** — metabolome + proteome + labs + microbiome on the same people.
5. **Microbiome mediation** — gut microbiome as mediator of a genotype/intervention -> blood effect.
6. **PRS stratification** — condition the method on polygenic risk.
(Extensible: sex-stratification and ΔAge-as-outcome are ready further candidates.)

## Principles
- Keep **forced adaptations** (data forces them) distinct from **value-add extensions** (chosen for
  novelty) in the write-up.
- Gate ethic: aggregates only; if the method yields per-person predictions, report the cross-validated
  metric, never rows.
- Never tune the Arivale analysis to make a validation cohort agree; grade every claim honestly.
