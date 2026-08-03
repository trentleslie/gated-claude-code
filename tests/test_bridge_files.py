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

def test_wrapper_reads_trusted_session_and_passes_it():
    # the differencing-monitor boundary must come from a trusted, unforgeable source and be
    # passed as an explicit arg, because `env -i` scrubs the environment. It prefers the
    # kernel audit login-session (distinct per concurrent analyst, write-once so cs-gated
    # cannot forge it) and falls back to the root-written launch file (Greptile P1 #3 and the
    # concurrent-session boundary follow-up).
    txt = (P / "run-analysis-wrapper").read_text()
    assert "/proc/self/sessionid" in txt          # primary, per-login boundary
    assert "/etc/gated-cs/session_id" in txt       # fallback when audit sessions are off
    assert "--session" in txt

def test_launcher_establishes_a_session_id():
    txt = (P / "bin" / "claude-arivale-launch").read_text()
    assert "/etc/gated-cs/session_id" in txt
    # generated per launch (unforgeable source), not inherited from the analyst's env
    assert "random/uuid" in txt

def test_submit_copies_into_shared_incoming_then_sudo():
    txt = (P / "submit-analysis").read_text()
    assert "/var/gate/incoming" in txt
    assert "exec sudo -u cs-exec /opt/gate/run-analysis" in txt

def test_submit_derivation_validates_layer_name():
    import subprocess, sys
    p = subprocess.run(["bash", "provision/submit-derivation", "x.py", "--layer", "bad;name"],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "layer name" in p.stderr
