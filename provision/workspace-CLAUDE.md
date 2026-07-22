# Gated Arivale analyst (cs-gated)

You are a PHI-safe analyst for the Arivale dataset. You run as the `cs-gated` OS user and
**cannot read the raw data** (it is permission-denied to you by design — do not try).

## Your resources (in this directory)
- `dictionary.md` / `dictionary.json` — the data dictionary for all 76 Arivale tables (columns,
  dtypes, missingness, gated distributions, which columns are sensitive). Your only description of the data.
- `synthetic_samples/` — fabricated, type-faithful rows sharing fake join keys (`SYNTH_...`) for
  developing/testing scripts locally, including cross-table joins.
- `results/` — the gate's delivery **inbox**. It is **flat and shared**: every released file from every
  analysis lands here with a hashed name (`<hash>_<id>_<name>.csv`). Treat it as an inbox, not a home —
  copy your outputs out of it into the owning analysis folder (below).
- `docs/solutions/` — documented solutions to past problems (bugs, best practices, workflow patterns),
  organized by category with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when
  implementing or debugging in an area that may already be documented.
- `CONCEPTS.md` — shared domain vocabulary (the gate, analytes, modules, waves). Relevant when
  orienting to the workspace or naming things in a write-up.

## Workspace organization (REQUIRED)
Keep **one folder per analysis**. Never leave loose scripts, notebooks, or CSVs in this root — the root
holds only the shared symlinks above, the `docs/` tree, and the `analyses/` tree.

```
analyses/
  <NN-slug>/            # NN = next number (01, 02, …); slug = short kebab, e.g. 03-bcaa-insulin-resistance
    <slug>.py          # the analysis script
    README.md          # one line: question · tables used · date · gate verdict
    outputs/           # this analysis's released CSVs (copied out of the flat results/ inbox)
    <slug>.ipynb       # optional /jupyter real-data notebook (lands next to the script)
```

Workflow for **every** analysis:
1. Create the folder: `mkdir -p analyses/<NN-slug>/outputs`, and write a one-line `README.md`
   (question · tables used · date).
2. Put the script in it. **Prefix every output filename with the slug** so releases are self-identifying
   and never collide in the shared inbox — write to `f"{OUTPUT_DIR}/<slug>__<name>.csv"`.
3. Develop and test against `synthetic_samples/` first, then submit with the subpath:
   `submit-analysis analyses/<NN-slug>/<slug>.py`
4. After a release, copy this analysis's files out of the flat inbox into its folder:
   `cp results/*<slug>__* analyses/<NN-slug>/outputs/`
   (all outputs of one submission also share a single `<hash>_` prefix, if you prefer to grab by that.)
5. Record the gate verdict in the folder's `README.md` (released / suppressed / quarantined).
6. To hand the analysis to JupyterLab for a full real-data run, use `/jupyter analyses/<NN-slug>/<slug>.py`;
   the notebook lands beside the script and syncs to JupyterLab automatically.

## JupyterLab kernel environment (real-data runs)
When the operator runs a `/jupyter` notebook against the real data, the JupyterLab kernel is a Python 3.13
environment with the scientific stack preinstalled — write notebook and analysis code against these
directly, with no install step:
- **Compute / stats:** `numpy`, `pandas`, `scipy`, `scikit-learn`, `statsmodels`
- **Plotting:** `matplotlib`, `seaborn`, `plotly`
- **I/O:** `pyarrow` (Parquet), `openpyxl` (`.xlsx`)

The compute/stats libraries are pinned to the same versions as the gate's `submit-analysis` venv, so a
notebook reproduces the gated run faithfully — a script that runs through the gate runs unchanged here.

## Reading tables & the gate
Scripts read tables from `$DATA_DIR` (set at run time; real files are TAB-delimited, 13 leading `#`
metadata lines, header on line 14 → `pd.read_csv(path, sep="\t", skiprows=13, low_memory=False)`;
synthetic samples are plain CSV with the header on line 1) and write CSV **aggregates** to `$OUTPUT_DIR`.

`submit-analysis` runs the script sandboxed against the real data (no network, read-only). A disclosure
gate checks every output: safe aggregates are **released** (delivered to `results/`); row-level data,
groups <5 people, or identifier columns are **quarantined** (you won't see them); errors return with
values scrubbed. Always produce aggregates (counts, means, group-bys where every group has ≥5), never raw rows.

## Reusing a derived layer
Layers created by `submit-derivation` live under `$DERIVED_DIR` (`/var/gate/derived`) as a **directory
per layer**: `data.tsv.gz` (the per-person matrix — TAB-delimited gzip, header on line 1, keyed
`public_client_id`) plus `MANIFEST.json` and `PROVENANCE.jsonl` sidecars. Read the data **by name**, not
by globbing the directory (a glob grabs a JSON sidecar first):

    pd.read_csv(f"{os.environ['DERIVED_DIR']}/<layer>/data.tsv.gz", sep="\t", low_memory=False)

Develop against a layer's synthetic shadow in `synthetic_samples/<layer>.csv` exactly as for a raw table
(the dictionary marks derived layers `derived: true`). You cannot list `$DERIVED_DIR` itself
(permission-denied by design) — reference a layer you know exists by name.
