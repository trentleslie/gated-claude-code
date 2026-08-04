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
    assert "DATA_DIR=/data/arivale" in txt
    assert ":=" not in txt  # not overridable via env
    assert "--audit /var/gate/audit.jsonl" in txt
    assert "--queue" in txt
    assert "--results /var/gate/results" in txt
    assert "run-analysis" in txt

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
