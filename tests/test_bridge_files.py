import pathlib
P = pathlib.Path(__file__).parent.parent / "provision"

def test_sudoers_is_narrow():
    txt = (P / "sudoers.d" / "cs-gated").read_text()
    assert "cs-gated ALL=(cs-exec) NOPASSWD: /opt/gate/run-analysis" in txt
    assert "ALL=(ALL)" not in txt

def test_run_analysis_wrapper_pins_trusted_paths():
    txt = (P / "run-analysis-wrapper").read_text()
    # sandbox now lives inside run_analysis, around only the child script; this
    # wrapper's job is to pin the trusted paths so cs-gated cannot override them.
    assert "bwrap" not in txt
    # the data path is a placeholder that provision.sh bakes in at install; the wrapper must
    # never take it from the environment or its arguments. Exactly one assignment, and it is
    # the placeholder (not "$1", "${DATA_DIR:-...}" or any other expansion).
    assigns = [l.split("#")[0].strip() for l in txt.splitlines() if l.lstrip().startswith("DATA_DIR=")]
    assert assigns == ["DATA_DIR=__GATED_CS_DATA_DIR__"]
    assert ":=" not in txt and ":-" not in txt  # not overridable via env
    prov = (P / "provision.sh").read_text()
    assert 's#__GATED_CS_DATA_DIR__#${DATA_DIR}#g' in prov         # substituted at install
    assert 'grep -q "^DATA_DIR=${DATA_DIR}\\b" /opt/gate/run-analysis' in prov   # and verified
    assert "--audit /var/gate/audit.jsonl" in txt
    assert "--queue" in txt
    assert "--results /var/gate/results" in txt
    assert "run-analysis" in txt

def _audit_log_setup_lines():
    return [l for l in (P / "provision.sh").read_text().splitlines() if "/var/gate/audit.jsonl" in l]

def test_provision_never_truncates_the_audit_log():
    lines = _audit_log_setup_lines()
    assert not any(">" in l.split("#")[0] for l in lines)      # no redirection onto the log
    assert any(l.split("#")[0].strip() == "touch /var/gate/audit.jsonl" for l in lines)  # create if absent
    joined = "\n".join(lines)
    assert "chown cs-exec:cs-exec /var/gate/audit.jsonl" in joined   # still enforced every run
    assert "chmod 0600 /var/gate/audit.jsonl" in joined

def test_reprovisioning_keeps_existing_audit_entries(tmp_path):
    # run provision.sh's own audit-log creation step twice against a log with history
    import subprocess
    log = tmp_path / "audit.jsonl"
    create = [l for l in _audit_log_setup_lines() if "chown" not in l and "chmod" not in l]
    assert create, "provision.sh no longer creates the audit log"
    script = "\n".join(create).replace("/var/gate/audit.jsonl", str(log))
    subprocess.run(["bash", "-euc", script], check=True)       # absent -> created
    assert log.exists()
    log.write_text('{"verdict": "allow"}\n')
    for _ in range(2):
        subprocess.run(["bash", "-euc", script], check=True)
    assert log.read_text() == '{"verdict": "allow"}\n'

def test_wrapper_derives_session_from_audit_login_with_failsafe_fallback():
    # the differencing-monitor boundary must come from a trusted, unforgeable source and be
    # passed as an explicit arg (`env -i` scrubs the environment). It is the kernel audit
    # login-session (distinct per concurrent analyst, write-once so cs-gated cannot forge it);
    # when unavailable the wrapper must NOT fall back to a shared host-global file (a
    # concurrent launch could overwrite it and split a campaign) but to no boundary =
    # artifact-only grouping, which over-groups but never splits.
    txt = (P / "run-analysis-wrapper").read_text()
    assert "/proc/self/sessionid" in txt          # unforgeable per-login boundary
    assert "/etc/gated-cs/session_id" not in txt   # no shared-file fallback (split risk)
    assert "--session" in txt

def test_derivation_wrapper_scopes_session_like_analysis():
    # the derivation path also emits artifact-decision audit records, so it must stamp the
    # same per-login session boundary as the analysis wrapper, or the differencing monitor
    # sees derivation activity unscoped (Greptile: derivation submissions remain unscoped).
    txt = (P / "run-derivation-wrapper").read_text()
    assert "/proc/self/sessionid" in txt
    assert "/etc/gated-cs/session_id" not in txt
    assert "--session" in txt

def test_launcher_writes_no_shared_session_file():
    # the launcher must not write a host-global session file: a concurrent launch could
    # overwrite it mid-session and split an ongoing campaign across boundaries. The per-login
    # boundary is derived by the wrappers from the kernel audit session instead.
    txt = (P / "bin" / "claude-arivale-launch").read_text()
    assert "session_id" not in txt

def test_submit_copies_into_shared_incoming_then_sudo():
    txt = (P / "submit-analysis").read_text()
    assert "/var/gate/incoming" in txt
    assert "exec sudo -u cs-exec /opt/gate/run-analysis" in txt

def test_submit_derivation_validates_layer_name():
    import subprocess, sys
    p = subprocess.run(["bash", "provision/submit-derivation", "x.py", "--layer", "bad;name"],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "layer name" in p.stderr


REQ = P / "requirements-gate.txt"
EXPORT = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project"]

def test_provision_installs_gate_venv_from_the_lock():
    # the gate venv must get the tested uv.lock versions, not whatever is newest on provisioning
    # day: hashed lock export first, then the package itself without re-resolving its deps
    txt = (P / "provision.sh").read_text()
    assert '--require-hashes -r "$SRC/provision/requirements-gate.txt"' in txt
    assert '--no-deps "$SRC"' in txt
    assert 'pip install --quiet "$SRC"' not in txt

def test_requirements_gate_matches_uv_lock():
    import shutil, subprocess, pytest
    if shutil.which("uv") is None:
        pytest.skip("uv not installed")
    root = P.parent
    out = subprocess.run(EXPORT, cwd=root, capture_output=True, text=True, check=True).stdout
    assert REQ.read_text() == out, (
        "provision/requirements-gate.txt is stale; regenerate with: "
        "uv export --frozen --no-dev --no-emit-project > provision/requirements-gate.txt")

def test_uv_lock_matches_pyproject():
    # --frozen exports the lock as-is, so the export check alone passes a lock that no longer
    # satisfies pyproject (e.g. a raised floor); with --no-deps the VM would keep the old pin
    import shutil, subprocess, pytest
    if shutil.which("uv") is None:
        pytest.skip("uv not installed")
    r = subprocess.run(["uv", "lock", "--check"], cwd=P.parent, capture_output=True, text=True)
    assert r.returncode == 0, "uv.lock is stale vs pyproject.toml; run `uv lock`, then regenerate " \
        "provision/requirements-gate.txt\n" + r.stderr[-500:]

def test_requirements_gate_covers_runtime_dependencies():
    import re
    try:
        import tomllib
    except ModuleNotFoundError:   # Python 3.10
        import tomli as tomllib
    deps = tomllib.loads((P.parent / "pyproject.toml").read_text())["project"]["dependencies"]
    pinned = {re.split(r"[=<> ;]", l, maxsplit=1)[0].lower() for l in REQ.read_text().splitlines()
              if l and not l.startswith((" ", "#"))}
    for d in deps:
        name = re.split(r"[=<>!~\[ ;]", d, maxsplit=1)[0].lower()
        assert name in pinned, f"{name} declared in pyproject but not pinned in requirements-gate.txt"
