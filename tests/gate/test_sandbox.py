from unittest.mock import patch
from gated_cs.gate import run_analysis as ra

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
