# `/apply-to-arivale` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two new gated-analyst skills — `apply-to-arivale` (transfer a frontier paper's method to Arivale with publication-value extensions, gate-run the discovery, route validation) and `tre-runpack` (emit human-run validation packs for non-exportable TREs) — authored in this repo and deployed to the box, and backfill the three existing box-only skills into version control.

**Architecture:** Skills are Markdown `SKILL.md` files plus small shipped helpers (a `reconcile.py`, two TRE run-pack templates) under `provision/skills/`. A `provision/bin/deploy-skills` rsyncs them to `cs-gated`'s `~/.claude/skills/`. Tests live in the repo (`tests/skills/`) and validate the helpers, templates, frontmatter, and deploy idempotency; the skills' prose behavior is human-accepted in the final task.

**Tech Stack:** Python ≥3.10 (pandas only — no new deps), bash, rsync-over-ssh, pytest. Emitted TRE artifacts are text templates (Python script / Jupyter notebook JSON) the human runs inside the TRE — never executed here.

## Global Constraints

- **Gate invariant unchanged:** `cs-gated` never reads raw rows; Arivale discovery runs go through `submit-analysis` and release only SDC-safe aggregates (every group **n ≥ 5**, wide-format, no identifier/date columns). This plan adds no new path out of the Arivale gate.
- **Each external TRE is an external gate:** emitted packs export only aggregates. **All of Us forbids any exported participant count of 1–20 → AoU packs enforce every group ≥ 21 or coarsen.** UKB-RAP uses UK Biobank return rules (floor `MIN_CELL = 5`, raise per DUA).
- **No new dependencies:** repo deps stay `pandas>=2.0` (+ `pytest>=8.0` dev). Use pandas for rank correlation (`method="spearman"`); do **not** import scipy or PyYAML.
- **Skills authored in `provision/skills/`, deployed to `cs-gated:~/.claude/skills/`** via `deploy-skills`.
- **Box access:** host `10.0.0.96` (drifts on reboot; override with `GCS_BOX`), user `root`, key `~/.ssh/id_ed25519_phenome` (override `GCS_KEY`). `cs-gated` home is `/home/cs-gated`.
- **Run tests with** `.venv/bin/pytest`.
- **Standardized TRE aggregate schema** (columns, in order): `feature,beta,se,n,metric,platform`.

---

### Task 1: Backfill existing box skills + skill-lint harness

**Files:**
- Create: `provision/skills/replicate/SKILL.md`, `provision/skills/validate/SKILL.md`, `provision/skills/method-kd-biological-age/SKILL.md` (captured verbatim from the box)
- Create: `tests/skills/__init__.py`, `tests/skills/test_skill_lint.py`

**Interfaces:**
- Produces: `tests/skills/test_skill_lint.py` defines `frontmatter_keys(path) -> set[str]`, reused conceptually by later content tests (each re-implements its own assertions; no shared import).

- [ ] **Step 1: Write the failing lint test**

Create `tests/skills/__init__.py` (empty) and `tests/skills/test_skill_lint.py`:

```python
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "provision" / "skills"

def frontmatter_keys(path: Path) -> set[str]:
    text = path.read_text()
    assert text.startswith("---"), f"{path}: missing frontmatter opener"
    end = text.index("\n---", 3)
    body = text[3:end]
    return {ln.split(":", 1)[0].strip() for ln in body.splitlines() if ":" in ln}

def test_skills_dir_exists():
    assert SKILLS_DIR.is_dir(), f"{SKILLS_DIR} not found"

def test_every_skill_has_valid_frontmatter():
    skills = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    assert skills, "no SKILL.md files found under provision/skills/"
    for s in skills:
        keys = frontmatter_keys(s)
        assert "name" in keys, f"{s}: frontmatter missing name"
        assert "description" in keys, f"{s}: frontmatter missing description"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/skills/test_skill_lint.py -v`
Expected: FAIL (`SKILLS_DIR not found` / no SKILL.md files).

- [ ] **Step 3: Capture the three existing skills verbatim from the box**

```bash
cd ~/projects/gated-claude-science
KEY=~/.ssh/id_ed25519_phenome ; BOX=root@10.0.0.96
for s in replicate validate method-kd-biological-age; do
  mkdir -p "provision/skills/$s"
  scp -i "$KEY" "$BOX:/home/cs-gated/.claude/skills/$s/SKILL.md" "provision/skills/$s/SKILL.md"
done
ls provision/skills/*/SKILL.md
```

- [ ] **Step 4: Run the lint test to verify it passes**

Run: `.venv/bin/pytest tests/skills/test_skill_lint.py -v`
Expected: PASS (3 skills lint clean).

- [ ] **Step 5: Commit**

```bash
git add provision/skills tests/skills
git commit -m "chore: backfill box skills into repo + skill-lint harness"
```

---

### Task 2: `deploy-skills` script + idempotency test

**Files:**
- Create: `provision/bin/deploy-skills`
- Create: `provision/skills/README.md`
- Create: `tests/skills/test_deploy_skills.py`

**Interfaces:**
- Produces: `provision/bin/deploy-skills [--dest DIR]` — no `--dest` rsyncs `provision/skills/` to `cs-gated:~/.claude/skills/` over ssh (env `GCS_BOX`, `GCS_KEY`); with `--dest DIR` rsyncs to a local dir (test hook). Idempotent.

- [ ] **Step 1: Write the failing idempotency test**

Create `tests/skills/test_deploy_skills.py`:

```python
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "provision" / "bin" / "deploy-skills"

def _run(dest: Path):
    return subprocess.run([str(DEPLOY), "--dest", str(dest)],
                          capture_output=True, text=True, check=True).stdout

def test_deploy_is_idempotent(tmp_path):
    first = _run(tmp_path / "skills")
    second = _run(tmp_path / "skills")
    # rsync -i marks sent files with a leading '>f'; a clean second run sends nothing.
    assert any(line.startswith(">f") for line in first.splitlines()), "first run copied nothing"
    assert not any(line.startswith(">f") for line in second.splitlines()), \
        f"second run not idempotent:\n{second}"

def test_deployed_tree_matches_source(tmp_path):
    dest = tmp_path / "skills"
    _run(dest)
    assert (dest / "replicate" / "SKILL.md").is_file()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/skills/test_deploy_skills.py -v`
Expected: FAIL (`deploy-skills` does not exist / not executable).

- [ ] **Step 3: Implement `deploy-skills`**

Create `provision/bin/deploy-skills`:

```bash
#!/usr/bin/env bash
# Deploy provision/skills/* to the gated box's cs-gated ~/.claude/skills (default),
# or to a local --dest DIR (for testing). Idempotent (rsync).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # -> provision/
SRC="$HERE/skills/"
DEST=""
SSH_HOST="${GCS_BOX:-10.0.0.96}"
KEY="${GCS_KEY:-$HOME/.ssh/id_ed25519_phenome}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="${2:?--dest needs a dir}"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
RSYNC_OPTS=(-ai --delete --exclude '__pycache__' --exclude '*.pyc')
if [ -n "$DEST" ]; then
  mkdir -p "$DEST"
  rsync "${RSYNC_OPTS[@]}" "$SRC" "$DEST/"
else
  CG="$(ssh -i "$KEY" "root@$SSH_HOST" 'getent passwd cs-gated | cut -d: -f6')"
  [ -n "$CG" ] || { echo "cs-gated not found on $SSH_HOST" >&2; exit 1; }
  rsync "${RSYNC_OPTS[@]}" -e "ssh -i $KEY" "$SRC" "root@$SSH_HOST:$CG/.claude/skills/"
  ssh -i "$KEY" "root@$SSH_HOST" "chown -R cs-gated:cs-gated '$CG/.claude/skills'"
  echo "deployed to $SSH_HOST:$CG/.claude/skills"
fi
```

Then: `chmod +x provision/bin/deploy-skills`

Create `provision/skills/README.md`:

```markdown
# Gated-analyst skills

Source of truth for the skills deployed to `cs-gated`'s `~/.claude/skills/` on the gated box.
Edit here, then deploy: `provision/bin/deploy-skills` (rsync over ssh; env `GCS_BOX`, `GCS_KEY`).

- `apply-to-arivale/` — transfer a frontier paper's method to Arivale + route validation.
- `tre-runpack/` — emit human-run validation packs for non-exportable TREs (UKB-RAP, All of Us).
- `replicate/`, `validate/`, `method-kd-biological-age/` — backfilled from the box (captured verbatim).
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/skills/test_deploy_skills.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add provision/bin/deploy-skills provision/skills/README.md tests/skills/test_deploy_skills.py
git commit -m "feat: deploy-skills rsync script + idempotency test"
```

---

### Task 3: `tre-runpack` UKB-RAP reference + template

**Files:**
- Create: `provision/skills/tre-runpack/SKILL.md`
- Create: `provision/skills/tre-runpack/references/ukb-rap.md`
- Create: `provision/skills/tre-runpack/templates/ukb_rap_template.py`
- Create: `tests/skills/test_tre_templates.py`

**Interfaces:**
- Produces: `templates/ukb_rap_template.py` — a py_compile-valid script emitting `tre_aggregates.csv` with header `feature,beta,se,n,metric,platform`, containing `{{...}}` fill tokens and `MIN_CELL`.

- [ ] **Step 1: Write the failing template test**

Create `tests/skills/test_tre_templates.py`:

```python
import json, py_compile
from pathlib import Path

TRE = Path(__file__).resolve().parents[2] / "provision" / "skills" / "tre-runpack"
HEADER = "feature,beta,se,n,metric,platform"

def test_ukb_template_compiles(tmp_path):
    src = TRE / "templates" / "ukb_rap_template.py"
    py_compile.compile(str(src), cfile=str(tmp_path / "out.pyc"), doraise=True)

def test_ukb_template_contract():
    text = (TRE / "templates" / "ukb_rap_template.py").read_text()
    assert "tre_aggregates.csv" in text
    assert HEADER.replace(",", '", "') in text or HEADER in text
    assert "MIN_CELL" in text
    assert "{{" in text  # has fill tokens
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/skills/test_tre_templates.py -v`
Expected: FAIL (template file missing).

- [ ] **Step 3: Implement the SKILL.md, reference, and UKB template**

Create `provision/skills/tre-runpack/SKILL.md`:

```markdown
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
```

Create `provision/skills/tre-runpack/references/ukb-rap.md`:

```markdown
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
```

Create `provision/skills/tre-runpack/templates/ukb_rap_template.py`:

```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/skills/test_tre_templates.py -v`
Expected: PASS (UKB tests green; AoU tests added in Task 4).

- [ ] **Step 5: Commit**

```bash
git add provision/skills/tre-runpack tests/skills/test_tre_templates.py
git commit -m "feat: tre-runpack skill + UKB-RAP reference and template"
```

---

### Task 4: `tre-runpack` All-of-Us reference + template (≥21 guard)

**Files:**
- Create: `provision/skills/tre-runpack/references/all-of-us.md`
- Create: `provision/skills/tre-runpack/templates/all_of_us_template.ipynb`
- Modify: `tests/skills/test_tre_templates.py` (add AoU cases)

**Interfaces:**
- Produces: `templates/all_of_us_template.ipynb` — valid nbformat-4 JSON; a code cell sets `MIN_CELL = 21` and writes `tre_aggregates.csv` with the standard header.

- [ ] **Step 1: Write the failing AoU tests**

Append to `tests/skills/test_tre_templates.py`:

```python
def test_aou_notebook_is_valid_json():
    nb = json.loads((TRE / "templates" / "all_of_us_template.ipynb").read_text())
    assert nb.get("nbformat") == 4
    assert isinstance(nb.get("cells"), list) and nb["cells"]

def test_aou_notebook_contract():
    nb = json.loads((TRE / "templates" / "all_of_us_template.ipynb").read_text())
    src = "\n".join("".join(c.get("source", [])) for c in nb["cells"])
    assert "MIN_CELL = 21" in src, "All of Us pack must enforce the >=21 small-cell rule"
    assert "tre_aggregates.csv" in src
    assert HEADER in src or HEADER.replace(",", '", "') in src
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/skills/test_tre_templates.py -v`
Expected: FAIL (AoU notebook missing).

- [ ] **Step 3: Implement the AoU reference and notebook**

Create `provision/skills/tre-runpack/references/all-of-us.md`:

```markdown
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
```

Create `provision/skills/tre-runpack/templates/all_of_us_template.ipynb`:

```json
{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# All of Us run-pack — RUN INSIDE the Researcher Workbench\n",
    "Reproduce an Arivale discovery statistic on All of Us and export ONLY aggregates.\n",
    "Row-level egress is blocked; every exported group must have n >= 21. Fill every {{TOKEN}}."
   ]
  },
  {
   "cell_type": "code",
   "execution_count": null,
   "metadata": {},
   "outputs": [],
   "source": [
    "import pandas as pd\n",
    "\n",
    "PLATFORM = \"all-of-us\"\n",
    "METRIC = \"{{METRIC}}\"\n",
    "OUTPUT_CSV = \"tre_aggregates.csv\"\n",
    "MIN_CELL = 21  # All of Us: no exported participant count 1-20\n",
    "\n",
    "# {{QUERY}} -> load cohort features into `pheno` (dataset builder / BigQuery).\n",
    "pheno = pd.DataFrame()  # replace with the Workbench dataset read\n",
    "\n",
    "def fit(pheno):\n",
    "    # {{MODEL}}: return one row per feature -> feature, beta, se, n\n",
    "    raise NotImplementedError('fill {{MODEL}} with the transferred method')\n",
    "\n",
    "res = fit(pheno)\n",
    "res = res[res[\"n\"] >= MIN_CELL].copy()\n",
    "res[\"metric\"] = METRIC\n",
    "res[\"platform\"] = PLATFORM\n",
    "res[[\"feature\", \"beta\", \"se\", \"n\", \"metric\", \"platform\"]].to_csv(OUTPUT_CSV, index=False)\n",
    "print(f\"wrote {OUTPUT_CSV}: {len(res)} features\")"
   ]
  }
 ],
 "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
 "nbformat": 4,
 "nbformat_minor": 5
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/skills/test_tre_templates.py -v`
Expected: PASS (UKB + AoU).

- [ ] **Step 5: Commit**

```bash
git add provision/skills/tre-runpack tests/skills/test_tre_templates.py
git commit -m "feat: tre-runpack All of Us reference and notebook with >=21 guard"
```

---

### Task 5: `reconcile.py` helper

**Files:**
- Create: `provision/skills/tre-runpack/reconcile.py`
- Create: `tests/skills/test_reconcile.py`

**Interfaces:**
- Produces: `reconcile(arivale: pd.DataFrame, tre: pd.DataFrame) -> dict` with keys `shared_features`, `direction_concordance`, `effect_rank_spearman`, `replication_rate`. Effect column is `beta` or `effect`. Also runnable as `python reconcile.py <arivale.csv> <tre.csv>`.

- [ ] **Step 1: Write the failing reconcile test**

Create `tests/skills/test_reconcile.py`:

```python
import importlib.util
from pathlib import Path
import pandas as pd

_p = Path(__file__).resolve().parents[2] / "provision" / "skills" / "tre-runpack" / "reconcile.py"
_spec = importlib.util.spec_from_file_location("reconcile", _p)
reconcile_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reconcile_mod)

def test_perfect_concordance():
    a = pd.DataFrame({"feature": ["m1", "m2", "m3"], "beta": [0.5, -0.3, 0.2]})
    t = pd.DataFrame({"feature": ["m1", "m2", "m3"], "beta": [0.4, -0.6, 0.1]})
    r = reconcile_mod.reconcile(a, t)
    assert r["shared_features"] == 3
    assert r["direction_concordance"] == 1.0
    assert r["effect_rank_spearman"] > 0.9

def test_partial_and_effect_column_alias():
    a = pd.DataFrame({"feature": ["m1", "m2", "m3", "m4"], "beta": [0.5, -0.3, 0.2, 0.9]})
    t = pd.DataFrame({"feature": ["m1", "m2", "m3"], "effect": [0.4, 0.6, 0.1]})  # m2 flips
    r = reconcile_mod.reconcile(a, t)
    assert r["shared_features"] == 3            # m4 not shared
    assert abs(r["direction_concordance"] - 2/3) < 1e-9

def test_no_overlap():
    a = pd.DataFrame({"feature": ["x"], "beta": [1.0]})
    t = pd.DataFrame({"feature": ["y"], "beta": [1.0]})
    r = reconcile_mod.reconcile(a, t)
    assert r["shared_features"] == 0
    assert r["direction_concordance"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/skills/test_reconcile.py -v`
Expected: FAIL (`reconcile.py` missing).

- [ ] **Step 3: Implement `reconcile.py`**

Create `provision/skills/tre-runpack/reconcile.py`:

```python
#!/usr/bin/env python3
"""Reconcile an Arivale discovery aggregate against a TRE-returned aggregate.

Both inputs share a `feature` column and a signed effect column (`beta` or `effect`).
Public-data / returned-aggregate analysis only — never touches the gate.
"""
from __future__ import annotations
import sys
import pandas as pd

_EFFECT_COLS = ("beta", "effect")


def _effect_col(df: pd.DataFrame) -> str:
    for c in _EFFECT_COLS:
        if c in df.columns:
            return c
    raise ValueError(f"no effect column {_EFFECT_COLS} in {list(df.columns)}")


def reconcile(arivale: pd.DataFrame, tre: pd.DataFrame) -> dict:
    ac, tc = _effect_col(arivale), _effect_col(tre)
    merged = arivale[["feature", ac]].rename(columns={ac: "a"}).merge(
        tre[["feature", tc]].rename(columns={tc: "t"}), on="feature"
    )
    n = len(merged)
    if n == 0:
        return {"shared_features": 0, "direction_concordance": None,
                "effect_rank_spearman": None, "replication_rate": None}
    same_sign = ((merged["a"] > 0) & (merged["t"] > 0)) | ((merged["a"] < 0) & (merged["t"] < 0))
    concordance = float(same_sign.mean())
    rank_r = float(merged["a"].corr(merged["t"], method="spearman")) if n >= 2 else None
    return {
        "shared_features": int(n),
        "direction_concordance": concordance,
        "effect_rank_spearman": rank_r,
        "replication_rate": concordance,
    }


def main() -> None:
    a, t = pd.read_csv(sys.argv[1]), pd.read_csv(sys.argv[2])
    for k, v in reconcile(a, t).items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/skills/test_reconcile.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add provision/skills/tre-runpack/reconcile.py tests/skills/test_reconcile.py
git commit -m "feat: tre-runpack reconcile helper (concordance / rank-corr / replication)"
```

---

### Task 6: `apply-to-arivale` orchestrator SKILL.md

**Files:**
- Create: `provision/skills/apply-to-arivale/SKILL.md`
- Create: `tests/skills/test_apply_to_arivale.py`

**Interfaces:**
- Consumes: `/validate`, `/tre-runpack`, `reconcile.py`, `method-kd-biological-age`, workspace conventions.
- Produces: a documented pipeline S0–S5 with a six-item extension catalog.

- [ ] **Step 1: Write the failing content test**

Create `tests/skills/test_apply_to_arivale.py`:

```python
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "provision" / "skills" / "apply-to-arivale" / "SKILL.md"

def test_frontmatter_trigger():
    text = SKILL.read_text()
    assert text.startswith("---")
    head = text[: text.index("\n---", 3)].lower()
    assert "name:" in head and "apply-to-arivale" in head
    assert "/apply-to-arivale" in text

def test_pipeline_stages_present():
    text = SKILL.read_text()
    for stage in ("S0", "S1", "S2", "S3", "S4", "S5"):
        assert stage in text, f"missing stage {stage}"

def test_extension_catalog_and_handoffs():
    text = SKILL.read_text().lower()
    for ext in ("longitudinal", "intervention", "cross-platform",
                "multi-omic", "microbiome mediation", "prs"):
        assert ext in text, f"extension '{ext}' not documented"
    assert "/validate" in text and "/tre-runpack" in text
    assert "method-kd-biological-age" in text        # reuse for aging-clock papers
    assert "submit-analysis" in text                 # gate discipline
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/skills/test_apply_to_arivale.py -v`
Expected: FAIL (SKILL.md missing).

- [ ] **Step 3: Author `apply-to-arivale/SKILL.md`**

Create `provision/skills/apply-to-arivale/SKILL.md`:

```markdown
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/skills/test_apply_to_arivale.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full skills suite + commit**

Run: `.venv/bin/pytest tests/skills/ -v`
Expected: PASS (all skills tests).

```bash
git add provision/skills/apply-to-arivale tests/skills/test_apply_to_arivale.py
git commit -m "feat: apply-to-arivale orchestrator skill"
```

---

### Task 7: Deploy to box + human acceptance

**Files:** none (integration/ops task).

**Interfaces:**
- Consumes: `provision/bin/deploy-skills`, the five skills, the three staged papers on the box.

- [ ] **Step 1: Deploy the skills to the box**

Run: `provision/bin/deploy-skills`
Expected: `deployed to 10.0.0.96:/home/cs-gated/.claude/skills`

- [ ] **Step 2: Verify all five skills are present for cs-gated**

```bash
ssh -i ~/.ssh/id_ed25519_phenome root@10.0.0.96 \
  'ls /home/cs-gated/.claude/skills | grep -E "apply-to-arivale|tre-runpack|replicate|validate|method-kd-biological-age"'
```
Expected: all five names listed.

- [ ] **Step 3: Human acceptance — dry-run S0–S2 (no gate spend)**

As `cs-gated` on the box (`claude-arivale-remote`), run
`/apply-to-arivale papers/zhang2024_metabolomic_aging_clock.pdf --tre both` and confirm it:
- writes a well-formed `analyses/<NN-slug>/README.md` application spec (method + novel Arivale question);
- lists forced adaptations (NMR-vs-Metabolon platform gap);
- proposes the ranked extension menu and **stops before any `submit-analysis`**.

This is a manual gate: do not proceed to S3 unattended.

- [ ] **Step 4: Commit any doc fixes surfaced during acceptance**

```bash
git add -A && git commit -m "docs: apply-to-arivale acceptance fixes" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- Two new skills authored in `provision/skills/`, deployed to box → Tasks 3–6 (author), Task 2 (deploy), Task 7 (deploy+verify). ✓
- Orchestrator pipeline S0–S5 → Task 6 SKILL.md + content test. ✓
- `tre-runpack` with grounded UKB-RAP + AoU execution models, external-gate ethic, AoU ≥21 → Tasks 3–4. ✓
- Standardized `tre_aggregates.csv` schema → Tasks 3–5 (templates + reconcile) enforce `feature,beta,se,n,metric,platform`. ✓
- Reconcile (concordance/rank-corr/replication) → Task 5. ✓
- Six-item extension catalog (+2 candidates) → Task 6 content test. ✓
- Reuse of `method-kd-biological-age` for aging-clock papers → Task 6 asserted. ✓
- Backfill existing three skills into version control → Task 1. ✓
- `deploy-skills` + idempotency → Task 2. ✓
- Gate ethic / provenance honesty → Task 6 SKILL.md prose. ✓
- Non-goals (human-run packs, no new export path, no auto-promotion) → encoded in skill prose, not violated by any task. ✓

**Placeholder scan:** the `{{TOKEN}}` strings in the TRE templates are intentional fill points (validated by tests), not plan placeholders; every code/test step contains complete content. ✓

**Type consistency:** `reconcile()` keys (`shared_features`, `direction_concordance`, `effect_rank_spearman`, `replication_rate`) are consistent between Task 5's implementation and test; the `feature,beta,se,n,metric,platform` header is identical across Tasks 3, 4, 5, and the Global Constraints. ✓
