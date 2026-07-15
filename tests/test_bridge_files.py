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
    assert "run-analysis" in txt

def test_submit_calls_sudo_cs_exec():
    txt = (P / "submit-analysis").read_text()
    assert "sudo -u cs-exec /opt/gate/run-analysis" in txt
