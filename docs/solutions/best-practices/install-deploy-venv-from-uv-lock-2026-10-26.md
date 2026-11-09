---
title: "Install a deploy venv from uv.lock: hashed export, --no-deps, a lock-freshness check, and a test on the target interpreter"
date: 2026-10-26
last_updated: 2026-11-06
category: best-practices
module: provision
problem_type: best_practice
component: tooling
severity: high
applies_when:
  - A provisioning script, Dockerfile or Ansible role runs pip install on a uv-locked project
  - Adding or raising a runtime dependency that the gate venv imports
  - Writing tests that guard a committed lock export against drift
  - The deploy interpreter (VM Python 3.10) is older than the dev interpreter
  - A doc or skill promises a package in the gate venv, or hand-installed fleet versions are being written into pyproject
  - Running gate tests from a throwaway venv
symptoms:
  - "provision.sh ran pip install \"$SRC\", so each VM got the pandas/numpy/pyarrow that was newest on its provisioning day"
  - "uv export --frozen passed with a raised pyproject floor and a stale lock; --no-deps would have kept the old pin on the VM"
  - "A test used tomllib, which does not exist on Python 3.10, the project floor"
  - "System python3.10 -m venv failed locally (ensurepip missing), blocking the target-interpreter check"
  - "scikit-learn, scipy and statsmodels were promised by workspace-CLAUDE.md and the replicate skill but undeclared, so a lock-strict provision shipped without them"
  - "Exact pins at the July fleet versions would downgrade numpy on Python 3.12+ (scipy 1.15.3 requires numpy<2.5)"
  - "A test venv under /tmp gave 16 extra gate-test failures (status error, not released/queued)"
root_cause: missing_workflow_step
resolution_type: workflow_improvement
related_components: [testing_framework, development_workflow]
tags: [uv-lock, reproducible-deploy, require-hashes, pip-no-deps, lock-freshness, provisioning, python-3-10, gate-venv, version-floors, bwrap-sandbox]
---

# Install a deploy venv from uv.lock: hashed export, --no-deps, a lock-freshness check, and a test on the target interpreter

## Context

Before PR #16 (commits `e84891b`, fix `6d07db4`, merge `420a807`), step 6 of `provision/provision.sh` built the gate venv with `pip install "$SRC"`. pip reads only the `pyproject.toml` floors (`pandas>=2.0`, `pyarrow>=14`) and never `uv.lock`, so each VM ran whatever was newest for its Python on the day it was provisioned, nothing recorded what that was, and none of it was the version set the tests passed against. No VM is known to have broken from this, but the gate venv has failed this way before: a missing scipy broke Spearman correlations in July 2026 (auto memory [claude]). PR #19 (merge `034be95`, 2026-11-06) then declared the stats stack, so a fresh provision now gets it too (Guidance 5).

## Guidance

**1. Export the lock as a hashed, marker-aware requirements file and commit it.**

```bash
uv export --frozen --no-dev --no-emit-project > provision/requirements-gate.txt
```

The export keeps the lock's per-Python splits (`pandas==2.3.3 ; python_full_version < '3.11'`, `pandas==3.0.3 ; python_full_version >= '3.11'`), so one file serves the Python 3.10 VMs and newer dev machines. As of PR #19 it has 26 hashed pins covering 20 packages (numpy and scipy appear three times, pandas and scikit-learn twice, once per Python split). Regenerate it in the same commit as any `uv.lock` change; the tests enforce this when `uv` is present.

**2. Install the pins with hash checking, then the package with `--no-deps`, then record what landed.** The last three lines of `provision.sh` step 6, after the venv is created and pip upgraded:

```bash
/opt/gated-cs/bin/pip install --quiet --require-hashes -r "$SRC/provision/requirements-gate.txt"
/opt/gated-cs/bin/pip install --quiet --no-deps "$SRC"
/opt/gated-cs/bin/pip freeze > /opt/gated-cs/installed-versions.txt   # what this box actually runs
```

`--no-deps` matters: pins that satisfy the `pyproject.toml` floors would be left alone anyway, but when the export and `pyproject.toml` disagree (a raised floor, a dependency missing from the export) pip would quietly install an unpinned, unhashed version, since `--require-hashes` applied only to the first command. With `--no-deps` the mismatch is left for the tests in step 3 to catch. The freeze file is the per-box record to compare against the lock later.

**3. Guard each link of the lock-to-VM chain with a test** (`tests/test_bridge_files.py`):

| Test | Catches |
|---|---|
| `test_provision_installs_gate_venv_from_the_lock` | `provision.sh` reverting to an unlocked install |
| `test_requirements_gate_matches_uv_lock` | export stale vs the lock (byte-equal to a fresh `uv export`) |
| `test_uv_lock_matches_pyproject` | lock stale vs `pyproject.toml` (`uv lock --check`) |
| `test_requirements_gate_covers_runtime_dependencies` | a declared dependency missing from the export |

The third one is the non-obvious one, and Greptile found it: `uv export --frozen` exports the lock as-is without checking it against `pyproject.toml`. Raise a floor without re-running `uv lock` and the export test still passes, because export and lock still agree; then `--no-deps` keeps the old pin on the VM. `uv lock --check` exits 1 on exactly that case and never writes the lock.

**4. Verify on the target interpreter, not the dev one.** The lock resolves differently per Python, and tests can depend on the stdlib version (`tomllib` exists only from 3.11; the coverage test falls back to `tomli`, added to the dev extra as `tomli>=1.1; python_version < '3.11'`). Reusable recipe:

```bash
# run step 6 for real in a throwaway venv on the target Python line; the subshell keeps
# set -e, cd and the cleanup trap from leaking into your shell
(
  set -e
  ROOT=$(git rev-parse --show-toplevel); cd "$ROOT"
  V=$(mktemp -d -p "$ROOT" .verify-venv.XXXXXX)   # inside the repo, not /tmp: see the gotcha below
  trap 'rm -rf "$V" "$ROOT/build"' EXIT   # `pip install .` leaves build/ in the repo
  uv venv -q --seed -p 3.10 --python-preference only-managed "$V/venv"
  "$V/venv/bin/pip" install -q --require-hashes --only-binary :all: -r provision/requirements-gate.txt
  "$V/venv/bin/pip" install -q --no-deps .
  "$V/venv/bin/pip" freeze | grep -Ei '^(pandas|numpy|pyarrow|scikit-learn|scipy|statsmodels)=='
  "$V/venv/bin/python" -c "from gated_cs.profiler.build_dictionary import build; import sklearn, scipy.stats, statsmodels.api"
)
```

`--only-binary :all:` makes the install fail if any pin lacks a wheel for this Python and platform, instead of quietly building from source as the VM would.

Result on Python 3.10.16 (rerun 2026-11-06, after PR #19): pandas 2.3.3, numpy 2.2.6, pyarrow 25.0.1, scikit-learn 1.7.2, scipy 1.15.3, statsmodels 0.15.0; profiler and stats stack import. Gotcha: the workstation's system `python3.10 -m venv` failed because Debian ships `ensurepip` separately (`python3.10-venv`). The VMs get it from `provision.sh` line 27 (`apt-get install ... python3-venv`); locally, `uv venv --seed --python-preference only-managed` sidesteps it. A uv-managed 3.10.16 is the same Python line as the VMs' 3.10.12, not an identical interpreter.

**Gotcha: keep a test venv out of `/tmp`.** To run the full suite on the target line, install pytest (plus `tomli` on 3.10) into the same venv and run `"$V/venv/bin/python" -m pytest -q`. With the venv under `/tmp`, 16 extra tests in `tests/gate/test_run_analysis.py`, `tests/gate/test_redteam.py` and `tests/service/test_api.py` fail with status `error` instead of `released` or `queued`. They are not gate regressions: `run_analysis` runs the child under `bwrap` with the interpreter it derives from `sys.prefix` / `sys.executable` (`src/gated_cs/gate/run_analysis.py`), and the sandbox mounts a fresh tmpfs over `/tmp`, so an interpreter living there does not exist inside it. With the venv inside the repo, PR #19's run on 3.10 and 3.12 gave 240 passed and the 2 failures that master already has (`test_exemplar_impute`, `test_run_analysis_wrapper_pins_trusted_paths`).

**5. Declare every package the gate venv promises, as floors at the fleet's versions, not exact pins.** Under steps 1-2, `pyproject.toml` alone decides what a fresh box gets; a package that docs promise and old VMs have from hand-installs is simply absent. PR #19 closed this for the stats stack:

```toml
dependencies = ["pandas>=2.0", "pyarrow>=14", "scikit-learn>=1.7.2", "scipy>=1.15.3", "statsmodels>=0.14.6"]
```

Check `requires_dist` before choosing pins. `curl -4 -s https://pypi.org/pypi/scipy/1.15.3/json | jq '.info.requires_python, .info.requires_dist'` shows scipy 1.15.3 requires `numpy<2.5`, while the lock holds numpy 2.5.1 on Python 3.12+, so `scipy==1.15.3` would downgrade numpy there. Newest releases also drop old Pythons (scikit-learn 1.9.1 needs 3.11+, scipy 1.18.1 needs 3.12+). Floors let the universal lock fork per Python marker. After `uv lock` and re-export, `grep -nE '^(scikit-learn|scipy|statsmodels|numpy)==' provision/requirements-gate.txt` shows the forks:

| Python | scikit-learn | scipy | numpy | statsmodels |
|---|---|---|---|---|
| 3.10 | 1.7.2 | 1.15.3 | 2.2.6 | 0.15.0 |
| 3.11 | 1.9.1 | 1.17.1 | 2.4.6 | 0.15.0 |
| 3.12+ | 1.9.1 | 1.18.1 | 2.5.1 | 0.15.0 |

Floors at the July versions are not July parity: a 3.10 box gets statsmodels 0.15.0, where the July fleet runs 0.14.6. If exact parity matters for one package, pin that one and leave the rest as floors.

## Why This Matters

- A lock only helps if the deploy path reads it. `uv sync` honors `uv.lock`; `pip install <path>` and `uv pip install ...` do not.
- In a gated TRE, the analyst develops against synthetic data on one environment and the gate runs the script on another. Unpinned gate packages make "passes on synthetic, fails in the gate" depend on provisioning date.

## When to Apply

- Any provisioning path that runs `pip install .` or `pip install <path>` on a uv-locked project.
- Whenever the target Python differs from the dev Python.

## Examples

`provision.sh` step 6, before:

```bash
/opt/gated-cs/bin/pip install --quiet "$SRC"
```

After: the three lines in Guidance 2.

## Open items (as of 2026-11-06)

- ~~**Stats stack not declared**~~ **Resolved 2026-11-06 by PR #19** (Guidance 5). `provision/skills/replicate/SKILL.md` (lines 51-52) is now true on a fresh provision. `provision/workspace-CLAUDE.md` (lines 55-56) says the notebook kernel has the stats stack "pinned to the same versions as the gate's `submit-analysis` venv"; nothing in this repo builds that kernel, and the gate side now varies by Python line, so that claim is unverified.
- **Existing VMs unchanged:** they keep their unlocked venvs until re-provisioned. A box is lock-installed only if `/opt/gated-cs/installed-versions.txt` exists.
- **The package install is still unlocked:** `pyproject.toml` has no `[build-system]`, so `pip install --no-deps "$SRC"` builds in an isolated environment that fetches the newest setuptools from PyPI without hashes. It is the last unpinned download in step 6 and needs network. Declaring `[build-system]` and pinning setuptools would close it.
- **Freshness tests need uv:** `test_requirements_gate_matches_uv_lock` and `test_uv_lock_matches_pyproject` skip when `uv` is not on PATH, so on such a host only the string and coverage tests run.

## Related

- `docs/solutions/best-practices/parquet-input-format-disclosure-controlled-profiler-2026-10-26.md` (section 6: a dependency isn't deployed until it's in the gate venv)
- `docs/solutions/documentation-gaps/verify-doc-claims-against-code-2026-10-26.md` (item 6: version claims checked against the lock and interpreter)
- Vault `docs/solutions/workflow-issues/unversioned-deploy-config-drift-2026-07-06.md` (deploy target drifting from the repo)
- `~/docs/solutions/runtime-errors/birdcheck-venv-orphaned-by-os-python-upgrade-2026-06-21.md` (a venv is tied to the interpreter that built it)
- PRs: https://github.com/trentleslie/gated-claude-code/pull/16 (lock install), https://github.com/trentleslie/gated-claude-code/pull/19 (stats stack as floors)
