from gated_cs.gate.audit import AuditLog

def test_append_and_read(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    i1 = log.record({"script_hash": "abc", "verdict": "allow"})
    i2 = log.record({"script_hash": "def", "verdict": "block"})
    e = log.entries()
    assert len(e) == 2 and e[0]["id"] == i1 and e[1]["id"] == i2
    assert e[0]["script_hash"] == "abc"
    assert e[1]["script_hash"] == "def"
    assert e[1]["verdict"] == "block"


def test_entries_missing_file_returns_empty(tmp_path):
    # entries() on a log that was never written must return [] (not crash) -
    # downstream consumers call this before the first record()
    assert AuditLog(str(tmp_path / "nope.jsonl")).entries() == []
