---
title: "Verify doc claims against the code before publishing: flags from argparse, examples from the test, guarantees as named checks plus gaps, versions from the lock"
date: 2026-10-26
category: documentation-gaps
module: gated_cs.profiler
problem_type: documentation_gap
component: documentation
severity: high
applies_when:
  - Writing docs/solutions, onboarding or wiki text that names CLI flags, invariants, disclosure guarantees, version-dependent behavior, or a command readers run to verify them
  - Answering a collaborator (Slack, email, call) about how to onboard data or what a command accepts
  - Writing a doc example that mirrors an existing regression test
  - Describing what an SDC or re-identification check proves
  - Triaging automated review findings on a doc-only PR
symptoms:
  - "Doc offered --join-keys as a profiling alternative; build-dictionary only takes data_dir and --out"
  - "Doc example asserted bin count only, omitting the n_subjects >= k the real test asserts"
  - "Doc called the offline re-id pass 'disclosure is actually safe'; it never intersects contributor sets"
  - "Doc said a pandas 3.1 test failure hits any new environment; the lock and the VMs' Python 3.10 both rule 3.1 out"
  - "Doc's own uv.lock check (grep -A4) showed 1 of 9 resolution markers, hiding the Python >= 3.11 split"
root_cause: inadequate_documentation
resolution_type: documentation_update
related_components: [tooling, testing_framework]
tags: [doc-accuracy, claim-verification, cli-flags, sdc, overclaiming, greptile, review-verification, version-claims]
---

# Verify doc claims against the code before publishing: flags from argparse, examples from the test, guarantees as named checks plus gaps, versions from the lock

## Context

PR #10 (commits `a5b95f5`, fix `85a731d`, merge `764cc14`) was doc-only: it added the parquet onboarding doc and committed the SDC nondisclosure-gate doc. Greptile scored it 4/5 with three findings. All three held up against the code, were fixed, and the re-review scored 5/5. Each was fluent, plausible prose written from intent rather than from the code:

1. **Flag on the wrong command.** The onboarding list said a dataset needs "a recognizable subject key ... or an explicit `--join-keys`". `build-dictionary` (`build_dictionary.py` `main()`) accepts only `data_dir` and `--out`; the subject key is detected by column name (`subject_key.detect_subject_key`) with no override. `--join-keys` exists only on `build-synthetic`, where it changes `SYNTH_` remapping. The same wrong answer had already gone to a collaborator in Slack before the doc existed, so the error was outside the repo first.
2. **Example weaker than the test.** The triangulation example asserted only `b["count"] >= DEFAULTS.bin_min_count`. The production guard keeps a bin only when count and `n_subjects` both clear the floor (`temporal_dist.py` ~64-67), and `tests/profiler/test_temporal_dist.py:121` asserts `n_subjects >= k`. The example dropped exactly the check the doc warned about: one heavy subject filling a bin.
3. **Guarantee overstated.** The doc called the offline re-id pass "disclosure is actually safe". `scripts/offline_reid_assess.py` counts distinct contributors per disclosed element and tallies cross-file sole contributors (`sole_hits`). It never intersects contributor sets, so two elements with five contributors each that share one person go undetected.

## Guidance

**1. Name a flag only after reading the argparse of the command you attribute it to.**

```bash
grep -n "def main\|def synthetic_main\|add_argument" src/gated_cs/profiler/build_dictionary.py
# main():           data_dir, --out
# synthetic_main(): --dictionary, --out, --join-keys, --id-pool-size
```

Write the command next to the flag (`build-synthetic --join-keys`). When a behavior has no override, say so ("detected by column name only, no override") so readers don't fill the gap with a guess. Copy enumerations from the source (`SUBJECT_KEY_CANDIDATES` has 7 names; the first draft listed 5).

**2. Quote assertions from the real test with a path, don't paraphrase.** A simplified example must never check less than the production predicate. Diff the doc's conditions against the guard (`cnt >= bin_min_count and nsub >= k`) before publishing.

**3. Describe a check by what it computes, then its known gap.** Start from the checker's own docstring, then name one case it cannot catch. Use "passes the implemented per-element checks", not "is safe" or "proves". In a disclosure context the words are the control: a reader told "actually safe" skips the manual review that covers the gap.

**4. Verbal answers get the same bar, and the same correction.** Answers to collaborators are documentation that skipped review. When a doc fix contradicts something already said, correct it with the person too; fixing only the repo leaves the wrong instruction live where it's being used.

**5. Verify reviewer findings in both directions.** On PR #9 Greptile was mostly wrong on 1 of 5 findings; on PR #10 it was right on 3 of 3. Neither record justifies batch acceptance or batch dismissal. Open the cited symbol for each finding, then fix or reply with evidence. PR #13 and PR #14 added one more correct finding each. On this repo Greptile does re-review pushed fix commits, editing its summary in place ("Reviews (2)", new "Last reviewed commit"): PR #9's fix was re-reviewed about 37 minutes after the push and PR #10's about 4 minutes after, both 5/5. PRs #13 and #14 were merged 30 to 60 seconds after their fix push, so those fixes were checked only by their author. Before merging, confirm the summary's "Last reviewed commit" equals the head SHA, or say the fix is unreviewed. PR #15 met it: its only commit (`4295242`) was pushed at 03:00Z, reviewed at 5/5 at 03:14:25Z, and merged at 03:14:33Z. (An earlier version of this item said Greptile does not re-review fix commits. That was an unverified generalization from polls that gave up after 10 minutes; `gh api repos/<owner>/<repo>/issues/<n>/comments` refuted it.)

**6. Version and environment claims: say how the environment was built, then check the lock and the interpreter.** "Any new environment shows X" is a claim about dependency resolution, not about the one venv you saw it in. Record the install command (`uv sync` honors `uv.lock`; `uv pip install ...` and `pip install <path>` ignore it), the Python version, and the resolved version, then compare with the lock and with the package's own Python floor:

```bash
pip freeze | grep -i '^pandas'                          # what this venv has
grep '{ name = "pandas", version' uv.lock                # project's direct pins with their Python markers
grep -n 'pip install\|uv sync\|uv pip' provision/*.sh   # which installs bypass the lock
```

One observation supports "seen in <how it was built>", not "any". PR #13 needed two passes on one sentence: the first fix scoped the claim to unlocked installs but still said new VMs could hit it, missing that pandas 3.x needs Python >= 3.11 and the VMs run 3.10.12. Open-items sections are claims too and get the same check.

**7. A verification command is a claim too: run it and confirm its output shows what the text says.** A fixed-context grep (`grep -A N`) cuts off variable-length blocks without warning. On PR #14 the check in item 6 was `grep -A4 '^name = "pandas"' uv.lock`, which printed 1 of pandas 3.0.3's 9 `resolution-markers` (win32, Python >= 3.14) and hid the >= 3.11 split the prose relied on. The fix (`10f1c14`) targets the line that carries the whole fact: the project's direct dependency entries, one complete marker per pinned version.

## Why This Matters

- In a PHI TRE, overstated safety wording changes behavior: people skip the checks the wording says are unnecessary.
- A weakened example teaches the wrong invariant, and future tests get written from the doc.
- Onboarding instructions reach external collaborators. A wrong flag makes them rename nothing, run profiling, and get files with no subject linkage, or reach for a command that does something else.
- Doc prose gets less scrutiny than code precisely because it reads well. All three errors were internally consistent; only a code cross-check caught them.

## When to Apply

- Before merging any doc that names flags, config keys, env vars, invariants or guarantees.
- Before answering "what do you need from me?" for dataset onboarding.
- When a doc example mirrors a test.
- On any doc-only PR touching disclosure or security claims: it is worth a review even though it has no code.

## Examples

Flag attribution (`best-practices/parquet-input-format-disclosure-controlled-profiler-2026-10-26.md`):

- Before: "A recognizable subject key (`subject_id`, `participant_id`, `public_client_id`, `record_id`, `id`, ...) or an explicit `--join-keys`."
- After: "A recognizable subject-key column name (`time_traveler_id`, `subject_id`, `participant_id`, `public_client_id`, `user_id`, `record_id`, `id`). Profiling (`build-dictionary`) detects it by name only and has no override; `--join-keys` exists only on `build-synthetic` ..."

Weakened invariant (`best-practices/synthetic-data-sdc-mechanical-nondisclosure-gate-2026-07-22.md`):

```diff
 for b in td[hist_key]:
     assert b["count"] >= DEFAULTS.bin_min_count
+    assert b["n_subjects"] >= DEFAULTS.k   # one heavy subject can fill a bin on its own
```

Version claim (`best-practices/parquet-...md`, open items), three versions:

- PR #13 as opened: "with pandas 3.1, ... fails ... any newly built environment shows it."
- After Greptile (`d378a89`): scoped to unlocked installs, "so newly provisioned VMs can hit it."
- Corrected: lock splits pandas 2.3.3 (< 3.11) / 3.0.3 (>= 3.11); pandas 3.x needs Python >= 3.11, so the 3.10.12 VMs cannot get it; only unlocked installs on >= 3.11 reach 3.1.

Verification command that hid its own evidence (PR #14, `fef3239` -> `10f1c14`):

```text
$ grep -A4 '^name = "pandas"' uv.lock          # before: 3.0.3 block cut after its first marker
...
version = "3.0.3"
resolution-markers = [
    "python_full_version >= '3.14' and sys_platform == 'win32'",
$ grep '{ name = "pandas", version' uv.lock    # after
    { name = "pandas", version = "2.3.3", ..., marker = "python_full_version < '3.11'" },
    { name = "pandas", version = "3.0.3", ..., marker = "python_full_version >= '3.11'" },
```

Overstated guarantee (same file):

- Before: the offline re-id assessment as "disclosure is actually safe."
- After: "the real cohort passes the implemented per-element checks." plus the named intersection gap.

## Open items (as of 2026-10-26)

- Unconfirmed whether the `--join-keys` correction has reached the collaborator who received the original answer.
- `scripts/offline_reid_assess.py` still does not intersect contributor sets across elements. That is an unfixed code gap, not a decision; only the wording was corrected.
- Wiki pages (`docs/wiki/gated-analysis-what-we-built`, `gated-analysis-setup-guide`) describe instances as reproduced identically and freshly provisioned boxes as self-contained. The gate code is identical, but the venv is installed unlocked (see the parquet doc's open items), so package versions follow the provisioning date. Worth a qualifier when those pages are next touched.
- `security/host-boundary-scope.md` says re-id risk "is assessed offline" without the per-element qualifier. Accurate but unqualified; worth the same one-line scoping if that doc is next touched.

## Related

- `docs/solutions/best-practices/parquet-input-format-disclosure-controlled-profiler-2026-10-26.md` (section 5, the PR #9 reviewer-verification data point)
- `docs/solutions/best-practices/synthetic-data-sdc-mechanical-nondisclosure-gate-2026-07-22.md` (canonical statement of what the CI gate and the offline assessor do and do not prove)
- Vault `docs/solutions/best-practices/absent-evidence-is-unverifiable-not-wrong-2026-08-06.md` (claimed assurance exceeding what a check covers, biomapper2)
- PR: https://github.com/trentleslie/gated-claude-code/pull/10
