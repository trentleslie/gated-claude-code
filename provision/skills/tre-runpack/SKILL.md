---
name: tre-runpack
description: Generate a self-contained, HUMAN-RUN validation pack for a non-exportable Trusted Research Environment (UK Biobank RAP or All of Us) that reproduces an Arivale discovery statistic inside that platform and exports only disclosure-safe aggregates. Use when the user says "/tre-runpack <discovery-outputs> <platform>", or when /apply-to-arivale routes external validation to a cohort whose data cannot be downloaded.
---

# /tre-runpack — validation pack for a non-exportable TRE

Each TRE is an **external gate**: you cannot download its rows, so you generate code the human runs
*inside* the platform, which returns only aggregate model outputs. Treat the platform's disclosure rules
as at least as strict as our own gate.

## Input
- `/tre-runpack <discovery-outputs.csv> <platform>` where `<platform>` ∈ {`ukb-rap`, `all-of-us`}.
- `<discovery-outputs.csv>` is a released Arivale aggregate with a `feature` column and a signed
  `beta`/`effect` column (the signal to test).

## Steps
1. Read the platform reference (`references/<platform>.md`) for the current execution model.
2. Copy the matching template from `templates/` into
   `analyses/<NN-slug>/validation/<platform>/` and fill every `{{TOKEN}}`: the features to fetch, the
   field/concept ids, the model that reproduces the Arivale statistic, and the metric name.
3. Write a `README.md` beside it: exact setup/run/export steps from the reference, and the disclosure
   contract (aggregates only; UKB return rules for RAP; **≥21 per exported group for All of Us**).
4. Hand off to the human to run in the TRE. They return a `tre_aggregates.csv`
   (`feature,beta,se,n,metric,platform`) into that folder.
5. Reconcile with `reconcile.py` (see below) and record the headline in the analysis README.

## Reconcile
`python reconcile.py <arivale_discovery.csv> <tre_aggregates.csv>` prints shared-feature count,
direction concordance, effect-size rank correlation, and replication rate — the same criteria `/validate`
uses. Never tune the Arivale analysis to make the TRE agree.

## Principles
- Aggregates only leave the TRE; enforce the platform's small-cell floor in the emitted code.
- Map features across cohorts by stable identity (HMDB/KEGG/UniProt, not raw platform ids); document
  every cross-cohort mapping as an adaptation.
- A partial replication with a stated cause is a real result.
