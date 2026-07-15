import shutil
from unittest.mock import patch
import pytest
from gated_cs.gate import run_analysis as ra

requires_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap not installed")

def test_no_bwrap_when_unavailable():
    with patch.object(ra.shutil, "which", return_value=None):
        cmd = ra._child_command("/s.py", "/data", "/out")
    assert cmd[0] != "bwrap" and cmd[-1] == "/s.py"

def test_sandbox_isolates_net_data_and_excludes_audit():
    with patch.object(ra.shutil, "which", return_value="/usr/bin/bwrap"), \
         patch.dict(ra.os.environ, {}, clear=False):
        ra.os.environ.pop("GATED_CS_NO_SANDBOX", None)
        cmd = ra._child_command("/s.py", "/data/arivale", "/out")
    s = " ".join(cmd)
    assert cmd[0] == "bwrap"
    assert "--unshare-net" in cmd and "--unshare-pid" in cmd and "--new-session" in cmd
    # real data is read-only, output is the only writable bind
    assert "--ro-bind-try /data/arivale /data/arivale" in s
    assert "--bind /out /out" in s
    # the audit log / queue are NEVER mounted into the untrusted child's sandbox
    assert "audit.jsonl" not in s and "/var/gate/queue" not in s

def test_require_sandbox_fails_closed_when_bwrap_unavailable(tmp_path):
    # GATED_CS_REQUIRE_SANDBOX=1 must refuse to run (fail-closed) rather than silently
    # falling back to unsandboxed execution when bwrap is missing.
    script = tmp_path / "s.py"
    script.write_text("x = 1\n")
    with patch.object(ra.shutil, "which", return_value=None), \
         patch.dict(ra.os.environ, {"GATED_CS_REQUIRE_SANDBOX": "1"}, clear=False):
        r = ra.run(str(script), str(tmp_path / "data"), str(tmp_path / "out"),
                    str(tmp_path / "audit.jsonl"), str(tmp_path / "queue"))
    assert r["status"] == "error"
    assert "sandbox" in r["message"].lower()
    from gated_cs.gate.audit import AuditLog
    entries = AuditLog(str(tmp_path / "audit.jsonl")).entries()
    assert any(e.get("verdict") == "error" and "sandbox" in e.get("reason", "").lower() for e in entries)

@requires_bwrap
def test_sandboxed_script_cannot_open_audit_log(tmp_path):
    # LIVE: really invoke bwrap and confirm the child process cannot reach the host
    # audit log even though it exists right next to the script/out dirs on the host.
    audit = tmp_path / "audit.jsonl"
    audit.write_text("")  # exists on host, but must NOT be reachable inside the sandbox
    script = tmp_path / "s.py"
    script.write_text(
        "p = %r\n"
        "try:\n"
        "    open(p, 'a').write('TAMPER')\n"
        "except Exception:\n"
        "    pass\n" % str(audit))
    ra.run(str(script), str(tmp_path / "data"), str(tmp_path / "out"),
           str(audit), str(tmp_path / "queue"))
    assert "TAMPER" not in audit.read_text()   # child could not reach the host audit path

@requires_bwrap
def test_sandboxed_script_has_no_network(tmp_path):
    # LIVE: really invoke bwrap with --unshare-net and confirm a real socket connect
    # attempt from inside the sandbox fails, causing the child script to error out.
    script = tmp_path / "s.py"
    script.write_text(
        "import socket\n"
        "s = socket.socket(); s.settimeout(3)\n"
        "s.connect(('1.1.1.1', 80))\n")   # must fail under --unshare-net -> nonzero exit
    r = ra.run(str(script), str(tmp_path / "data"), str(tmp_path / "out"),
               str(tmp_path / "audit.jsonl"), str(tmp_path / "queue"))
    assert r["status"] == "error"   # network attempt failed -> script errored
