import pathlib
P = pathlib.Path(__file__).parent.parent / "provision"

def test_sudoers_is_narrow():
    txt = (P / "sudoers.d" / "cs-gated").read_text()
    assert "cs-gated ALL=(cs-exec) NOPASSWD: /opt/gate/run-analysis" in txt
    assert "ALL=(ALL)" not in txt

def test_run_analysis_wrapper_has_no_network_and_ro_data():
    txt = (P / "run-analysis-wrapper").read_text()
    assert "--unshare-net" in txt
    assert "--ro-bind" in txt and "DATA_DIR" in txt

def test_submit_calls_sudo_cs_exec():
    txt = (P / "submit-analysis").read_text()
    assert "sudo -u cs-exec /opt/gate/run-analysis" in txt
