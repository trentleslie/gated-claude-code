# `/apply-to-arivale` — Method-Transfer & External-Validation Skill — Design Spec

> **For agentic workers:** implement via `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans`, task-by-task.

**Goal:** Add a *generative* counterpart to the existing `/replicate` skill. Where `/replicate`
reproduces a published paper's **own** number on the gated Arivale data, `/apply-to-arivale` takes a
frontier paper's **method** and applies it to Arivale to produce a **new** result — deliberately adding
Arivale-native tweaks/extensions that raise publication value — then orchestrates external validation,
including against **non-exportable** cohorts (UK Biobank RAP, All of Us) that `/validate` cannot reach
today because their data cannot be downloaded into the workspace.

**Architecture:** Two new skills, authored in this repo under `provision/skills/` and deployed to
`cs-gated`'s `~/.claude/skills/`:
- **`apply-to-arivale`** — the orchestrator: paper → application spec → Arivale adaptation + value-add
  extensions → gate-run discovery → validation routing → synthesis/grade → optional method-module
  promotion.
- **`tre-runpack`** — a small, independently-invokable generator that emits a self-contained,
  **human-run** analysis pack for a non-exportable TRE, treating each TRE as an *external gate* (run code
  inside, export only disclosure-safe aggregates). Ships `references/ukb-rap.md` and
  `references/all-of-us.md` (web-researched execution models, cached).

The skill reuses the existing workspace grain unchanged: `analyses/<NN-slug>/` folders, synthetic→
`submit-analysis` development, aggregate-only gate outputs, `analyses/_lib/` primitives, `methods/<name>/`
verified modules (`provenance.json`), and `validation/<dataset>/` open cohorts for `/validate`.

**Tech stack:** Markdown skills (`SKILL.md` + `references/`); the gated analyst's existing Python gate
venv (`/opt/gated-cs`: pandas/numpy/scikit-learn/scipy/statsmodels); `dx-toolkit`/WDL and Jupyter/Terra
artifacts emitted as *text templates* (never executed here — the human runs them inside the TRE).

## Global constraints

- **The gate invariant is unchanged.** `cs-gated` never reads raw Arivale rows; discovery runs go through
  `submit-analysis` and release only SDC-safe aggregates (k≥5 per group, wide-format under the row cap, no
  identifier/date columns). `/apply-to-arivale` adds no new path out of the PHI boundary.
- **External validation data is public / lives outside our boundary.** Downloadable open cohorts are read
  directly in the workspace by `/validate` (no gate). Non-exportable TREs are *someone else's* gated
  environment — we never hold their row data; we generate code the human runs there, and only their
  aggregate outputs return to us.
- **Each TRE is treated as an external gate.** Emitted run-packs must obey the host platform's own
  disclosure rules, which are at least as strict as ours: UKB return rules for RAP; **All of Us forbids any
  exported participant count of 1–20**, so AoU packs enforce every group ≥ 21 or coarsen.
- **Discovery/validation split stays clean:** never tune the Arivale analysis to make an external cohort
  agree.

## Decisions (locked during brainstorming)

1. **Approach A** — orchestrator skill + a *separate, reusable* `tre-runpack` skill (not a single
   self-contained skill, not method-module-first).
2. **Both TREs in v1** — UKB-RAP (DNAnexus) and All of Us (Terra Workbench).
3. **Extension catalog** (§4) is the approved six, and is extensible (sex-stratification and
   ΔAge-as-outcome are named as ready further candidates).
4. **Backfill in scope** — the existing box-only skills (`replicate`, `validate`, `method-kd-biological-age`)
   are brought under repo version control alongside the two new skills.
5. **Papers already staged** (out of band, done): `wang2025_organ_proteomic_aging_clocks.pdf`,
   `zhang2024_metabolomic_aging_clock.pdf`, `woerner2025_prs_proteomic_incident_disease.pdf` in
   `~/analysis/papers/`, manifest-registered.

## 1. Skill surface & invocation

`/apply-to-arivale <paper.pdf> [--target <claim>] [--extension <angle>…] [--tre ukb-rap|all-of-us|both|none]`

- `<paper.pdf>` — a staged paper under `~/analysis/papers/` (frontier method source).
- `--target` — optional; which of the paper's methods/results to transfer if several.
- `--extension` — optional preselection from the §4 catalog; otherwise the skill proposes a ranked menu
  and stops for a human pick.
- `--tre` — which non-exportable platform(s) to generate validation packs for (`none` = open-cohort
  `/validate` only).

`/tre-runpack <discovery-outputs> <platform>` — standalone entry: given a released Arivale aggregate
(betas/effect sizes) and a platform, emit the run-pack (§3).

## 2. Orchestrator pipeline

Primary artifact is a standard `analyses/<NN-slug>/` folder.

- **S0 — Application spec.** Read the PDF (Read tool reads PDFs natively). Write to
  `analyses/<NN-slug>/README.md`: (a) the **method** (data layers, preprocessing, model/statistic, metric —
  as in `/replicate`); (b) the **novel Arivale question** the method unlocks (the literature gap being
  filled), which is what distinguishes an *application* spec from a *replication* spec. Full citation
  (authors, year, journal, DOI) from `papers/papers_manifest.csv`.
- **S1 — Map to Arivale** (reuse `/replicate`'s dictionary discipline). Resolve tables/columns from
  `dictionary.md`/`dictionary.json`, join key `public_client_id`, real-file read pattern
  (`sep="\t", skiprows=13`). Record every platform/panel gap (NMR vs Metabolon, Olink panel differences,
  16S vs shotgun; analyte names via `*_metadata`) as a **forced adaptation** — never a silent deviation.
- **S2 — Value-add extensions** (§4). Enumerate applicable extensions, each tagged with the publication
  value it adds, the **wave** it advances, and the **grade** it can reach; rank by value×feasibility.
  **Human checkpoint:** the analyst picks which to pursue before any gate spend.
- **S3 — Build + gate-run the discovery.** Standard workspace flow: `analyses/<NN-slug>/<slug>.py`,
  slug-prefixed wide-format aggregate outputs, develop against `synthetic_samples/`, then
  `submit-analysis`. Reuse `analyses/_lib/` primitives and existing `methods/<name>/` modules where they
  fit — **`method-kd-biological-age` is the ready-made backbone for the two aging-clock papers** (build the
  clock via the verified module, then apply longitudinal/intervention extensions on top).
- **S4 — Validation routing.**
  - Downloadable open cohort present/fetchable → hand the released discovery aggregate to **`/validate`**
    (direction concordance, effect-size rank correlation, replication rate).
  - Non-exportable TRE requested → **`/tre-runpack`** (§3) emits the pack; the human runs it inside the
    TRE and drops the returned `tre_aggregates.csv` into `analyses/<NN-slug>/validation/<platform>/`; a
    **reconcile** step scores it with the *same* criteria `/validate` uses.
- **S5 — Synthesize + grade.** README headline = Arivale discovery (with extensions) + external
  concordance + per-claim grade. **Optional promotion:** if the transferred method verifies and is
  reusable, promote it to `methods/<name>/` with `provenance.json` (paper, gate release hash,
  discovery-vs-source comparison) via the existing `build_catalog.py`/`validate_provenance.py` path.

## 3. `tre-runpack` — non-exportable-TRE generator

Given a released Arivale discovery aggregate and a platform, generate a **human-run** pack under
`analyses/<NN-slug>/validation/<platform>/` (a *per-analysis* validation subfolder — distinct from the
top-level `~/analysis/validation/<dataset>/` open-cohort cache that `/validate` reads) containing: (a) the analysis script/notebook that reproduces
the *same statistic* on the TRE cohort, (b) a `README.md` with exact setup/run/export steps and the
disclosure contract, (c) an expected-output schema. All packs emit one standardized
`tre_aggregates.csv` (shared columns: `feature`, `beta`/`effect`, `se`, `n`, `metric`, `platform`) so
reconcile is uniform across platforms.

- **`references/ukb-rap.md`** — DNAnexus RAP: no data download, work in-platform; `dx-toolkit`; tabular
  data as a dispensed Parquet dataset (`dx extract_dataset`, Spark instance if >30 fields);
  JupyterLab/RStudio/Swiss-Army-Knife apps; UKB-PPP Olink + Nightingale NMR field mapping; results
  (small aggregate CSV) downloadable from the project under UKB return rules. Pack = a plain
  Python/WDL script + `dx run` instructions + the aggregate-only output contract.
- **`references/all-of-us.md`** — All of Us Terra Workbench: Registered + Controlled tier (proteomics
  ~10k, WGS/arrays); Jupyter/RStudio; row-level egress blocked, summary downloadable under a size
  threshold; **hard small-cell rule: no exported participant count 1–20** → pack enforces every group ≥ 21
  or coarsens. Pack = a notebook + `README.md` respecting AoU egress.

Both reference files are **web-researched at authoring time and cached** (execution models drift; a
refresh note records the check date), so per-run generation does not re-derive the platform contract.

## 4. Publication-value extension catalog (the differentiator vs `/replicate`)

The catalog the skill applies to every paper; each chosen extension is tagged (value · wave · grade):

1. **Longitudinal trajectory** — within-person change over repeated draws (source papers are
   cross-sectional).
2. **Intervention pre/post response** — modifiability under the Arivale coaching arm.
3. **Cross-platform transfer** — Metabolon vs NMR, Olink panel differences (a harder, honest test).
4. **Multi-omic joint modeling** — combine metabolome + proteome + labs + microbiome on the same people.
5. **Microbiome mediation** — gut microbiome as mediator of a genotype→blood or intervention→blood effect.
6. **PRS stratification** — condition the transferred method on polygenic risk.

Extensible; **sex-stratification** and **ΔAge-as-outcome** are named ready additions. Each extension is
what turns "we re-ran a UKB method" into a novel, Arivale-only contribution.

## 5. Provenance, honesty & gate ethic

Same ethic as `replicate`/`validate`, made explicit in the SKILL.md:
- **Forced adaptations** (data forces them) are kept distinct from **value-add extensions** (we chose them
  for novelty) in the README.
- **Grade every claim**; a partial external replication with a stated cause is a real result, a
  suspiciously exact match earns scrutiny.
- Aggregates only out of the Arivale gate; if the source method yields per-person predictions, report the
  cross-validated metric, never rows.
- Never tune the Arivale discovery to make a validation cohort agree.

## 6. Repo layout, deploy & backfill

```
provision/skills/
  apply-to-arivale/SKILL.md
  tre-runpack/SKILL.md
  tre-runpack/references/ukb-rap.md
  tre-runpack/references/all-of-us.md
  replicate/SKILL.md            # backfilled from the box (verbatim capture)
  validate/SKILL.md             # backfilled
  method-kd-biological-age/SKILL.md   # backfilled
provision/bin/deploy-skills     # rsync provision/skills/* -> cs-gated ~/.claude/skills/, chown cs-gated
```

- `deploy-skills` is idempotent, runs as root over SSH to the box, rsyncs each skill dir into
  `~cs-gated/.claude/skills/`, and `chown -R cs-gated:cs-gated`. It prints what changed.
- Backfill first captures the three existing box skills into the repo **verbatim** (so version control
  reflects reality), then future edits flow repo→box via `deploy-skills`.

## 7. Testing

- **Skill lint:** `SKILL.md` frontmatter (`name`, `description`) present; description carries the
  invocation trigger; internal file references resolve.
- **Dry-run S0–S2 on a staged paper** (e.g. `zhang2024_metabolomic_aging_clock.pdf`): the skill produces a
  well-formed application spec + adaptation list + ranked extension menu **without** a gate submission
  (S3 is human-gated).
- **`tre-runpack` template validity:** generated UKB-RAP script parses under `python -m py_compile`; AoU
  notebook is valid JSON; both emit the standardized `tre_aggregates.csv` header; AoU pack contains the
  ≥21 small-cell guard.
- **Reconcile unit test:** given a synthetic Arivale aggregate and a synthetic `tre_aggregates.csv`,
  reconcile computes direction concordance + rank correlation + replication rate correctly.
- **`deploy-skills` idempotency:** second run is a no-op (no rsync changes).

## Non-goals / YAGNI (v1)

- No automated execution *inside* a TRE — packs are human-run (we hold no TRE credentials).
- No new export path from the Arivale gate; discovery uses `submit-analysis` unchanged.
- No third TRE beyond UKB-RAP and AoU (e.g., no dbGaP/Terra-generic, no MESA) in v1.
- No auto-promotion to a `methods/` module — promotion stays an explicit final step.
- The skill does not *pick* the paper or the gap; it operates on a staged paper.

## Dependencies / context this fits

- Sits beside the existing gated-analyst skills on the box: `/replicate` (reproduce), `/validate`
  (open-cohort check), `method-kd-biological-age` (verified method module), plus `orchestrate`, `jupyter`,
  `pickup`.
- Consumes the workspace conventions in `~/analysis/CLAUDE.md` + `CONCEPTS.md` (gate, analyte, module,
  wave, grade, derived layers) and the `papers/papers_manifest.csv` registry.
- The three frontier method-source papers are already staged and manifest-registered.
