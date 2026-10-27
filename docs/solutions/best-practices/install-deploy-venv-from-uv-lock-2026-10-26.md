---
title: "Install a deploy venv from uv.lock: hashed export, --no-deps, a lock-freshness check, and a test on the target interpreter"
date: 2026-10-26
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
symptoms:
  - "provision.sh ran pip install \"$SRC\", so each VM got the pandas/numpy/pyarrow that was newest on its provisioning day"
  - "uv export --frozen passed with a raised pyproject floor and a stale lock; --no-deps would have kept the old pin on the VM"
  - "A test used tomllib, which does not exist on Python 3.10, the project floor"
  - "System python3.10 -m venv failed locally (ensurepip missing), blocking the target-interpreter check"
root_cause: missing_workflow_step
resolution_type: workflow_improvement
related_components: [testing_framework, development_workflow]
tags: [uv-lock, reproducible-deploy, require-hashes, pip-no-deps, lock-freshness, provisioning, python-3-10, gate-venv]
---

# Install a deploy venv from uv.lock: hashed export, --no-deps, a lock-freshness check, and a test on the target interpreter

## Context

Before PR #16 (commits `e84891b`, fix `6d07db4`, merge `420a807`), step 6 of `provision/provision.sh` built the gate venv with `pip install "$SRC"`. pip reads only the `pyproject.toml` floors (`pandas>=2.0`, `pyarrow>=14`) and never `uv.lock`, so each VM ran whatever was newest for its Python on the day it was provisioned, nothing recorded what that was, and none of it was the version set the tests passed against. No VM is known to have broken from this, but the gate venv has failed this way before: a missing scipy broke Spearman correlations in July 2026 (auto memory [claude]).

## Guidance

**1. Export the lock as a hashed, marker-aware requirements file and commit it.**

```bash
uv export --frozen --no-dev --no-emit-project > provision/requirements-gate.txt
```

The export keeps the lock's per-Python splits (`pandas==2.3.3 ; python_full_version < '3.11'`, `pandas==3.0.3 ; python_full_version >= '3.11'`), so one file serves the Python 3.10 VMs and newer dev machines. It has 10 hashed pins covering 7 packages (numpy and pandas appear once per Python split). Regenerate it in the same commit as any `uv.lock` change; the tests enforce this when `uv` is present.

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
# run step 6 for real in a throwaway venv on the target Python line (from the repo root)
trap 'rm -rf /tmp/gate310 build/' EXIT   # `pip install .` leaves build/ in the repo
uv venv --seed -p 3.10 --python-preference only-managed /tmp/gate310
/tmp/gate310/bin/pip install -q --require-hashes --only-binary :all: -r provision/requirements-gate.txt
/tmp/gate310/bin/pip install -q --no-deps .
/tmp/gate310/bin/pip freeze | grep -Ei '^(pandas|numpy|pyarrow)=='
/tmp/gate310/bin/python -c "from gated_cs.profiler.build_dictionary import build"
```

`--only-binary :all:` makes the install fail if any pin lacks a wheel for this Python and platform, instead of quietly building from source as the VM would.

Result on Python 3.10.16: pandas 2.3.3, numpy 2.2.6, pyarrow 25.0.1, profiler imports. Gotcha: the workstation's system `python3.10 -m venv` failed because Debian ships `ensurepip` separately (`python3.10-venv`). The VMs get it from `provision.sh` line 27 (`apt-get install ... python3-venv`); locally, `uv venv --seed --python-preference only-managed` sidesteps it. A uv-managed 3.10.16 is the same Python line as the VMs' 3.10.12, not an identical interpreter.

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

## Open items (as of 2026-10-26)

- **Stats stack not declared:** scikit-learn, scipy and statsmodels are in neither `pyproject.toml` nor the lock, so a fresh provision still lacks them. The existing fleet has them from hand-pinning in July 2026 (1.7.2 / 1.15.3 / 0.14.6, auto memory [claude]); a version decision is pending. Until then, `provision/workspace-CLAUDE.md` (lines 55-56) and `provision/skills/replicate/SKILL.md` (lines 51-52), which promise that stack in the gate venv, are true on the existing VMs but false on a freshly provisioned one.
- **Existing VMs unchanged:** they keep their unlocked venvs until re-provisioned. A box is lock-installed only if `/opt/gated-cs/installed-versions.txt` exists.
- **The package install is still unlocked:** `pyproject.toml` has no `[build-system]`, so `pip install --no-deps "$SRC"` builds in an isolated environment that fetches the newest setuptools from PyPI without hashes. It is the last unpinned download in step 6 and needs network. Declaring `[build-system]` and pinning setuptools would close it.
- **Freshness tests need uv:** `test_requirements_gate_matches_uv_lock` and `test_uv_lock_matches_pyproject` skip when `uv` is not on PATH, so on such a host only the string and coverage tests run.

## Related

- `docs/solutions/best-practices/parquet-input-format-disclosure-controlled-profiler-2026-10-26.md` (section 6: a dependency isn't deployed until it's in the gate venv)
- `docs/solutions/documentation-gaps/verify-doc-claims-against-code-2026-10-26.md` (item 6: version claims checked against the lock and interpreter)
- Vault `docs/solutions/workflow-issues/unversioned-deploy-config-drift-2026-07-06.md` (deploy target drifting from the repo)
- `~/docs/solutions/runtime-errors/birdcheck-venv-orphaned-by-os-python-upgrade-2026-06-21.md` (a venv is tied to the interpreter that built it)
- PR: https://github.com/trentleslie/gated-claude-code/pull/16
