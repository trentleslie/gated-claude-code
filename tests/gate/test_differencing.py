"""Unit 2 — offline inference-by-differencing monitor.

Verifies the detective monitor flags rapid-iteration / threshold-search campaigns on a
synthetic audit log, passes a benign log, and — mirroring test_nondisclosure.py's intent —
that its report discloses only aggregate signals (counts, rates, positions, hashes, artifact
names), never a subject id, raw value, reason string, or script body.
"""
import json
import pytest
from gated_cs.gate.audit import AuditLog
from gated_cs.gate.differencing import analyze, run_report, MonitorConfig, main


def _write(tmp_path, entries, name="audit.jsonl"):
    log = AuditLog(str(tmp_path / name))
    for e in entries:
        log.record(e)
    return str(tmp_path / name)


def _artifact(h, verdict, artifact="r.csv", reason="x"):
    return {"script_hash": h, "artifact": artifact, "verdict": verdict, "reason": reason}


def test_benign_log_passes():
    # a handful of distinct scripts, mostly clean releases, no oscillation
    entries = [_artifact(f"h{i:02d}", "allow") for i in range(5)]
    entries += [{"script_hash": f"h{i:02d}", "verdict": "run", "released": 1, "queued": 0}
                for i in range(5)]
    report = analyze(entries)
    assert report["differencing_pass"] is True
    assert report["flagged_windows"] == []
    assert report["oscillation_flags"] == []


def test_rapid_iteration_under_suppression_is_flagged():
    # 12 distinct scripts, all landing on the suppression boundary in one burst -> probing
    entries = [_artifact(f"probe{i:02d}", "suppress", artifact=f"a{i}.csv") for i in range(12)]
    report = analyze(entries)
    assert report["differencing_pass"] is False
    assert report["flagged_windows"], "a rapid suppressed-iteration burst must flag a window"
    w = report["flagged_windows"][0]
    assert w["max_distinct_scripts"] >= MonitorConfig().min_distinct_scripts
    assert w["max_suppress_rate"] >= MonitorConfig().min_suppress_rate


def test_suppress_allow_oscillation_is_flagged():
    # threshold binary-search: the SAME output name flips allow<->suppress repeatedly
    seq = ["suppress", "allow", "suppress", "allow", "suppress", "allow"]
    entries = [_artifact(f"osc{i:02d}", v, artifact="probe.csv") for i, v in enumerate(seq)]
    report = analyze(entries)
    assert report["differencing_pass"] is False
    assert any(f["artifact"] == "probe.csv" and f["flips"] >= MonitorConfig().min_oscillations
               for f in report["oscillation_flags"])


def test_unrelated_runs_reusing_artifact_name_do_not_oscillate():
    # Greptile P1 #3: five independent submissions that happen to reuse the filename r.csv,
    # each with its own session / run / script_hash, must NOT be fused into one probing
    # campaign. Their allow/suppress transitions are unrelated activity, not a binary-search
    # on a suppression boundary, so no oscillation may be flagged.
    seq = ["allow", "suppress", "allow", "suppress", "allow"]
    entries = [{"script_hash": f"s{i}", "session": f"sess{i}", "run": f"run{i}",
                "artifact": "r.csv", "verdict": v, "reason": "x"}
               for i, v in enumerate(seq)]
    report = analyze(entries)
    assert report["oscillation_flags"] == []
    assert report["differencing_pass"] is True


def test_oscillation_within_one_session_is_still_flagged():
    # the fix must not blunt detection: a genuine threshold search flips the same artifact
    # allow<->suppress across successive submissions WITHIN one session -> still flagged.
    seq = ["suppress", "allow", "suppress", "allow", "suppress", "allow"]
    entries = [{"script_hash": f"s{i}", "session": "S", "artifact": "probe.csv",
                "verdict": v, "reason": "x"} for i, v in enumerate(seq)]
    report = analyze(entries)
    assert report["differencing_pass"] is False
    assert any(f["artifact"] == "probe.csv" and f["flips"] >= MonitorConfig().min_oscillations
               for f in report["oscillation_flags"])


def test_report_is_aggregate_only_no_leakage():
    # reason strings can name columns / values; the report must never echo them, or a subject
    # id, or a script body — only counts, rates, positions, hashes, and artifact names.
    secret_reason = "row 3 value SUBJECT_SENTINEL_42 = 1990-07-15"
    entries = [_artifact(f"probe{i:02d}", "suppress", artifact=f"a{i}.csv", reason=secret_reason)
               for i in range(12)]
    report = analyze(entries)
    blob = json.dumps(report)
    assert "SUBJECT_SENTINEL_42" not in blob
    assert "1990-07-15" not in blob
    assert secret_reason not in blob
    assert "reason" not in report  # top-level report carries no reason field


def test_empty_log_passes_with_note():
    report = analyze([])
    assert report["differencing_pass"] is True
    assert "note" in report


def test_missing_audit_file_does_not_crash(tmp_path):
    # AuditLog.entries() returns [] for a missing file; the monitor must pass cleanly
    report = run_report(str(tmp_path / "nope.jsonl"), str(tmp_path / "rep.json"))
    assert report["differencing_pass"] is True
    assert json.loads((tmp_path / "rep.json").read_text())["differencing_pass"] is True


def test_run_report_writes_file_and_returns(tmp_path):
    path = _write(tmp_path, [_artifact(f"probe{i:02d}", "suppress") for i in range(12)])
    report = run_report(path, str(tmp_path / "report.json"))
    written = json.loads((tmp_path / "report.json").read_text())
    assert written == report
    assert written["differencing_pass"] is False


def test_main_exit_code_signals_detection(tmp_path, monkeypatch):
    # exit 1 when a probing signature is flagged (so a scheduled run can alert), 0 otherwise
    probing = _write(tmp_path, [_artifact(f"probe{i:02d}", "suppress") for i in range(12)],
                     name="probing.jsonl")
    monkeypatch.setattr("sys.argv", ["gate-monitor", probing, str(tmp_path / "r1.json")])
    with pytest.raises(SystemExit) as ex:
        main()
    assert ex.value.code == 1

    benign = _write(tmp_path, [_artifact(f"h{i:02d}", "allow") for i in range(3)],
                    name="benign.jsonl")
    monkeypatch.setattr("sys.argv", ["gate-monitor", benign, str(tmp_path / "r2.json")])
    with pytest.raises(SystemExit) as ex:
        main()
    assert ex.value.code == 0
