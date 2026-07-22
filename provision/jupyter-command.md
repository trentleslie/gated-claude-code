---
description: Convert an analysis .py into a .ipynb that syncs to JupyterLab for a full real-data run by the operator
---
Convert the analysis script `$ARGUMENTS` into a Jupyter notebook so the operator can run it against the real data in JupyterLab.

1. Run: `to-notebook $ARGUMENTS`  — this writes `<script>.ipynb` beside the script (cells split on `# %%` markers).
2. The one-way workspace mirror surfaces it in JupyterLab automatically (under the mirrored copy of this workspace) within a couple of seconds.
3. Report the `.ipynb` path to the operator.

IMPORTANT: You (cs-gated) are permission-denied to the raw data by design — do NOT try to execute this notebook against real data. Only the operator runs it, inside JupyterLab, outside the gate. Keep developing your scripts against `synthetic_samples/` and validating aggregates through `submit-analysis`.
