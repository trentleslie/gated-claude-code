#!/usr/bin/env python3
"""Check a hypothesis lineage file (JSONL, one version per line) before it leaves the workspace.

Stdlib only. Usage: python3 check_record.py docs/hypotheses/<slug>.jsonl
Exit 0 when clean; otherwise prints one problem per line and exits 1.

Rules: SLE core fields present; x_stage2 extension values in the allowed sets; parent links
point to earlier versions in the same file; version ids unique; and free text never restates
numbers (Arivale values must be cited by released-output path, not copied into the record).
This is a backstop for the human egress review, not a replacement for it.
"""
import json
import re
import sys

SLE_CORE = ("version_id", "parents", "episode", "claim", "plan", "alternatives",
            "evidence", "critic_score", "critique", "selected")
EVIDENCE_STATES = {"settled", "contested", "speculative", "unanchored"}
RESOLVABILITY = {"resolvable", "partial", "not_resolvable", "undetermined"}
REPEAT = {"present", "absent", "unknown"}

# Spans removed before looking for numbers: backticked names, URLs, citation ids, released-output paths.
_EXEMPT = re.compile(
    r"`[^`]*`"
    r"|https?://\S+"
    r"|\bPMID:\s*\d+"
    r"|\bPMC\d+"
    r"|\bdoi:\s*10\.\S+"
    r"|\b10\.\d{4,}/\S+"
    r"|\bresults/\S+",
    re.I,
)
# A bare number: digits not attached to letters (so HbA1c, T2D, v2 pass), with optional . , : / parts.
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])\d+(?:[.,:/]\d+)*(?![A-Za-z0-9_])")


def _texts(rec):
    """Yield (field, text) for every free-text field the no-restated-numbers rule covers."""
    for f in ("claim", "plan", "evidence", "critique"):
        v = rec.get(f)
        if isinstance(v, str):
            yield f, v
    alts = rec.get("alternatives")
    for i, a in enumerate(alts if isinstance(alts, list) else [alts]):
        if isinstance(a, str):
            yield f"alternatives[{i}]", a
    x = rec.get("x_stage2") or {}
    for part in ("evidence_state", "resolvability"):
        for f in ("note", "missing"):
            v = (x.get(part) or {}).get(f)
            if isinstance(v, str):
                yield f"x_stage2.{part}.{f}", v


def _numbers(text):
    return _NUMBER.findall(_EXEMPT.sub(" ", text))


def check_records(records):
    errors, seen = [], set()
    for i, rec in enumerate(records, 1):
        vid = rec.get("version_id", f"<line {i}>")
        where = f"line {i} ({vid})"
        for f in SLE_CORE:
            if f not in rec:
                errors.append(f"{where}: missing SLE core field '{f}'")
        if vid in seen:
            errors.append(f"{where}: duplicate version_id '{vid}'")
        parents = rec.get("parents", [])
        if not isinstance(parents, list):
            errors.append(f"{where}: 'parents' must be a list")
            parents = []
        for p in parents:
            if p not in seen:
                errors.append(f"{where}: parent '{p}' is not an earlier version in this file")
        seen.add(vid)

        x = rec.get("x_stage2")
        if not isinstance(x, dict):
            errors.append(f"{where}: missing 'x_stage2' extension")
        else:
            es = (x.get("evidence_state") or {}).get("value")
            if es not in EVIDENCE_STATES:
                errors.append(f"{where}: evidence_state '{es}' not in {sorted(EVIDENCE_STATES)}")
            if not (x.get("evidence_state") or {}).get("source"):
                errors.append(f"{where}: evidence_state needs a 'source'")
            r = x.get("resolvability") or {}
            if r.get("value") not in RESOLVABILITY:
                errors.append(f"{where}: resolvability '{r.get('value')}' not in {sorted(RESOLVABILITY)}")
            if r.get("repeat_measurements") not in REPEAT:
                errors.append(f"{where}: resolvability.repeat_measurements must be one of {sorted(REPEAT)}")
            if not isinstance(r.get("variables"), list):
                errors.append(f"{where}: resolvability.variables must be a list of backticked names")
            if r.get("value") == "undetermined" and not (r.get("missing") or "").strip():
                errors.append(f"{where}: resolvability 'undetermined' needs 'missing' to name what is unknown")

        for field, text in _texts(rec):
            nums = _numbers(text)
            if nums:
                errors.append(f"{where}: {field} restates numbers {nums}; cite a released output "
                              f"instead, and backtick variable names")
    return errors


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: check_record.py <lineage.jsonl>", file=sys.stderr)
        return 2
    records = []
    with open(argv[0]) as fh:
        for n, line in enumerate(fh, 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"line {n}: not valid JSON ({e})")
                    return 1
    errors = check_records(records)
    for e in errors:
        print(e)
    if not errors:
        print(f"ok: {len(records)} version(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
