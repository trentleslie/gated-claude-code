"""Offline detective monitor for inference-by-differencing / boundary-probing campaigns.

The release gate is deterministic, so RAND's rerun-until-success dynamic cannot defeat the
barrier itself — but it reappears at the release *decision*: an agent can iterate analysis
scripts to binary-search a suppression threshold (nudge a cell around k until it flips from
`suppress` to `allow`) and thereby infer a suppressed value. The append-only audit log
records enough to detect this after the fact; this monitor does.

It is DETECTIVE, not preventive: it never touches the release hot path and adds no state to
it. It reads the audit log, computes aggregate campaign signals, and writes an aggregate-only
JSON report — mirroring `scripts/offline_reid_assess.py`'s discipline: only counts, rates,
sequence positions, and the script hashes the audit already stores. Never a subject id, a raw
value, a reason string, or a script body.

The audit log carries no timestamps, so windows are taken over append order (which is
chronological for an append-only log) rather than wall-clock time.

Usage:  gate-monitor <AUDIT_PATH> <REPORT_PATH>
        python -m gated_cs.gate.differencing <AUDIT_PATH> <REPORT_PATH>
Exit code: 0 when differencing_pass is True, 1 when a probing signature is flagged (so a
scheduled run can route an alert); the report always lands on disk regardless.
"""
import argparse, json, sys
from dataclasses import dataclass
from .audit import AuditLog

# Verdicts that represent a per-artifact release decision (the surface a differencing
# campaign probes). Run-level, error, timeout, and derivation entries are excluded.
_RELEASE_VERDICTS = {"allow", "suppress", "block", "unclassifiable"}
_SUPPRESSED = {"suppress", "block", "unclassifiable"}   # "did not fully release"


@dataclass(frozen=True)
class MonitorConfig:
    window: int = 10                 # consecutive artifact decisions per sliding window
    min_distinct_scripts: int = 8    # distinct scripts in a window that reads as rapid iteration
    min_suppress_rate: float = 0.5   # fraction of a window sitting on the suppression boundary
    min_oscillations: int = 4        # allow<->suppress flips on one artifact name = threshold search


def _flag_windows(artifact_entries, cfg):
    """Sliding-window scan for rapid script iteration under suppression pressure, merged
    into non-overlapping index ranges so one campaign is reported once, not once per slide."""
    n = len(artifact_entries)
    raw = []
    if n >= cfg.window:
        for start in range(0, n - cfg.window + 1):
            win = artifact_entries[start:start + cfg.window]
            distinct = len({e.get("script_hash") for e in win})
            sb = sum(1 for e in win if e.get("verdict") in _SUPPRESSED)
            rate = sb / len(win)
            if distinct >= cfg.min_distinct_scripts and rate >= cfg.min_suppress_rate:
                raw.append((start, start + cfg.window, distinct, rate))
    merged = []
    for start, end, distinct, rate in raw:
        if merged and start <= merged[-1]["end_index"]:
            m = merged[-1]
            m["end_index"] = max(m["end_index"], end)
            m["max_distinct_scripts"] = max(m["max_distinct_scripts"], distinct)
            m["max_suppress_rate"] = round(max(m["max_suppress_rate"], rate), 4)
        else:
            merged.append({"start_index": start, "end_index": end,
                           "max_distinct_scripts": distinct, "max_suppress_rate": round(rate, 4)})
    return merged


def _oscillation_flags(artifact_entries, cfg):
    """Per artifact NAME, count allow<->suppressed flips across successive submissions. A
    binary-search on a suppression threshold shows up as repeated boundary crossings on the
    same output name. Only the artifact name (already stored in cleartext in the audit log,
    never PHI) and the flip count are emitted."""
    seqs = {}
    for e in artifact_entries:
        seqs.setdefault(e.get("artifact"), []).append(e.get("verdict"))
    flags = []
    for artifact, verdicts in seqs.items():
        states = ["released" if v == "allow" else "suppressed" for v in verdicts]
        flips = sum(1 for a, b in zip(states, states[1:]) if a != b)
        if flips >= cfg.min_oscillations:
            flags.append({"artifact": artifact, "flips": flips, "submissions": len(verdicts)})
    return flags


def analyze(entries, cfg=MonitorConfig()):
    artifact_entries = [e for e in entries
                        if e.get("artifact") is not None and e.get("verdict") in _RELEASE_VERDICTS]
    distinct_scripts = len({e.get("script_hash") for e in entries if e.get("script_hash")})
    flagged_windows = _flag_windows(artifact_entries, cfg)
    oscillation_flags = _oscillation_flags(artifact_entries, cfg)
    report = {
        "differencing_pass": not (flagged_windows or oscillation_flags),
        "total_entries": len(entries),
        "artifact_decisions": len(artifact_entries),
        "distinct_scripts": distinct_scripts,
        "config": {"window": cfg.window, "min_distinct_scripts": cfg.min_distinct_scripts,
                   "min_suppress_rate": cfg.min_suppress_rate,
                   "min_oscillations": cfg.min_oscillations},
        "flagged_windows": flagged_windows,
        "oscillation_flags": oscillation_flags,
    }
    if not entries:
        report["note"] = "empty or missing audit log — nothing to analyze"
    return report


def run_report(audit_path, report_path, cfg=MonitorConfig()):
    import os
    report = analyze(AuditLog(audit_path).entries(), cfg)
    os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[differencing] differencing_pass={report['differencing_pass']}  "
          f"flagged_windows={len(report['flagged_windows'])}  "
          f"oscillation_flags={len(report['oscillation_flags'])}")
    print(f"[differencing] report written to {report_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="Offline inference-by-differencing monitor.")
    ap.add_argument("audit", help="path to the append-only audit log (jsonl)")
    ap.add_argument("report", help="path to write the aggregate-only JSON report")
    a = ap.parse_args()
    report = run_report(a.audit, a.report)
    sys.exit(0 if report["differencing_pass"] else 1)


if __name__ == "__main__":
    main()
