import pathlib
import pytest
from gated_cs.gate.review import list_pending, approve, reject
from gated_cs.gate.audit import AuditLog

def _seed(tmp_path):
    q = tmp_path / "queue"; q.mkdir()
    (q / "a.csv").write_text("group,count\nx,3\n")
    return str(q)

def test_list_and_approve(tmp_path):
    q = _seed(tmp_path); res = str(tmp_path / "results"); pathlib.Path(res).mkdir()
    assert list_pending(q) == ["a.csv"]
    approve("a.csv", q, res, str(tmp_path / "audit.jsonl"))
    assert (pathlib.Path(res) / "a.csv").exists()
    assert list_pending(q) == []

def test_reject_removes(tmp_path):
    q = _seed(tmp_path)
    reject("a.csv", q, str(tmp_path / "audit.jsonl"))
    assert list_pending(q) == []

def test_list_pending_includes_non_csv(tmp_path):
    # Task 10's executor quarantines non-csv artifacts too (fail-closed for
    # unclassifiable output types), so the reviewer must see every regular
    # file in the queue, not just *.csv, or non-csv leaks would sit
    # unreviewed forever.
    q = tmp_path / "queue"; q.mkdir()
    (q / "abc_raw.json").write_text('{"x": 1}')
    assert list_pending(str(q)) == ["abc_raw.json"]

def test_approve_non_csv(tmp_path):
    q = tmp_path / "queue"; q.mkdir()
    (q / "abc_raw.json").write_text('{"x": 1}')
    res = tmp_path / "results"; res.mkdir()
    dest = approve("abc_raw.json", str(q), str(res), str(tmp_path / "audit.jsonl"))
    assert dest == str(res / "abc_raw.json")
    assert (res / "abc_raw.json").exists()
    assert list_pending(str(q)) == []

def test_reject_non_csv(tmp_path):
    q = tmp_path / "queue"; q.mkdir()
    (q / "abc_raw.json").write_text('{"x": 1}')
    reject("abc_raw.json", str(q), str(tmp_path / "audit.jsonl"))
    assert list_pending(str(q)) == []

def test_reject_path_traversal_is_contained(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("keep me")
    q = tmp_path / "queue"; q.mkdir()
    with pytest.raises(FileNotFoundError):
        reject("../secret.txt", str(q), str(tmp_path / "audit.jsonl"))
    assert outside.exists()   # traversal did not delete the outside file

def test_approve_writes_audit_entry(tmp_path):
    q = tmp_path / "queue"; q.mkdir()
    (q / "a.csv").write_text("group,count\nx,3\n")
    res = tmp_path / "results"
    audit = tmp_path / "audit.jsonl"
    approve("a.csv", str(q), str(res), str(audit))
    entries = AuditLog(str(audit)).entries()
    assert any(e.get("verdict") == "review:approve" and e.get("artifact") == "a.csv" for e in entries)

def test_reject_writes_audit_entry(tmp_path):
    q = tmp_path / "queue"; q.mkdir()
    (q / "b.csv").write_text("group,count\ny,2\n")
    audit = tmp_path / "audit.jsonl"
    reject("b.csv", str(q), str(audit))
    entries = AuditLog(str(audit)).entries()
    assert any(e.get("verdict") == "review:reject" and e.get("artifact") == "b.csv" for e in entries)
