# Hypothesis record format

One JSONL file per hypothesis lineage, one version per line: `docs/hypotheses/<slug>.jsonl`.
Versions are append-only. A revision is a new line whose `parents` names the version it develops;
earlier lines are never edited.

## SLE core fields (names unchanged)

Taken verbatim from Science's Last Exam, `docs/HYPOTHESIS_DISCOVERY.md` (DiscoveryRSI harness), so
records stay readable by that tooling.

| Field | Type | Meaning |
|---|---|---|
| `version_id` | string | Unique within the file, e.g. `cer-v1` |
| `parents` | list of strings | Earlier `version_id`s in this file that this version develops; `[]` for the first |
| `episode` | integer | Research episode that produced the version |
| `claim` | string | The hypothesis, stated so it can be wrong |
| `plan` | string | Investigation plan, including the **comparator or measurement** and the **falsification criterion** (what result would count against the claim) |
| `alternatives` | list of strings | Alternative explanations to rule out |
| `evidence` | string | What supports or challenges the claim: literature citations and cited released outputs, never restated numbers |
| `critic_score` | number | Critic's score for this version (a rating of the hypothesis, not Arivale data) |
| `critique` | string | The critic's assessment |
| `selected` | boolean | Whether this version is carried forward |

## Our extension: `x_stage2`

Kept under one namespaced key so the SLE core stays untouched.

| Field | Values | Meaning |
|---|---|---|
| `evidence_state.value` | `settled` / `contested` / `speculative` / `unanchored` | State of the literature at the strongest study design: settled (already answered), contested (supported only by weaker designs, or null at the stronger one), speculative (indirect support only), unanchored (nothing to judge plausibility) |
| `evidence_state.source` | string | Where the call came from, e.g. a Paperclip evidence link or a PMC/PMID citation |
| `evidence_state.note` | string | One line, no numbers |
| `resolvability.value` | `resolvable` / `partial` / `not_resolvable` / `undetermined` | Can Arivale data test the claim? |
| `resolvability.variables` | list | Backticked dictionary variable names that would test it |
| `resolvability.repeat_measurements` | `present` / `absent` / `unknown` | `present` only when `find_vars.py` reports `longitudinal: present` (the profiler saw repeat events per participant); otherwise `unknown`. A date range alone (temporal coverage) is not evidence of repeat draws |
| `resolvability.missing` | string | Required when `undetermined`: the fact the dictionary could not answer |
| `resolvability.note` | string | One line, no numbers |

`not_resolvable` needs positive evidence that the data cannot test the claim (a needed variable is
absent). A missing longitudinal facet is never enough: that is `undetermined`.

## Writing rules

- Never restate Arivale numbers anywhere in a record. Cite released outputs by path
  (`results/<file>.csv`) and literature by PMC/PMID/DOI or link.
- Put every dictionary variable name in backticks, e.g. `Cer(d18:1/16:0)`.
- Run the checker before calling a record done:
  `python3 ~/.claude/skills/hypothesize/check_record.py docs/hypotheses/<slug>.jsonl`

## Example (one version)

```json
{"version_id": "example-v1", "parents": [], "episode": 1, "claim": "Higher `Cer(d18:1/16:0)` precedes a decline in physical function.", "plan": "Comparator: participants with and without later decline. Measurement: `Cer(d18:1/16:0)` at the earliest draw. Falsification: no association once age and statin use are adjusted for.", "alternatives": ["Statin use lowers ceramides and tracks with care intensity."], "evidence": "Cross-sectional support; longitudinal null in ARIC (PMC7806657).", "critic_score": 6, "critique": "Plausible and testable if repeat draws exist.", "selected": true, "x_stage2": {"evidence_state": {"value": "contested", "source": "PMC7806657", "note": "Supported cross-sectionally, null longitudinally."}, "resolvability": {"value": "undetermined", "variables": ["`Cer(d18:1/16:0)`"], "repeat_measurements": "unknown", "missing": "Whether participants have repeat metabolomics draws.", "note": "Species present; draw structure not profiled."}}}
```
