from gated_cs.gate.audit import AuditLog

def test_append_and_read(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    i1 = log.record({"script_hash": "abc", "verdict": "allow"})
    i2 = log.record({"script_hash": "def", "verdict": "block"})
    e = log.entries()
    assert len(e) == 2 and e[0]["id"] == i1 and e[1]["id"] == i2
    assert e[0]["script_hash"] == "abc"
