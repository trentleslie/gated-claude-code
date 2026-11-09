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


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _type_errors(rec, where):
    """Documented field types: anything else could carry structured values past the text scan."""
    errs = []
    for f in ("version_id", "claim", "plan", "evidence", "critique"):
        if f in rec and not isinstance(rec[f], str):
            errs.append(f"{where}: '{f}' must be a string")
    for f in ("parents", "alternatives"):
        if f in rec and not (isinstance(rec[f], list) and all(isinstance(v, str) for v in rec[f])):
            errs.append(f"{where}: '{f}' must be a list of strings")
    if "episode" in rec and not (isinstance(rec["episode"], int) and not isinstance(rec["episode"], bool)):
        errs.append(f"{where}: 'episode' must be an integer")
    if "critic_score" in rec and not _is_num(rec["critic_score"]):
        errs.append(f"{where}: 'critic_score' must be a number")
    if "selected" in rec and not isinstance(rec["selected"], bool):
        errs.append(f"{where}: 'selected' must be true or false")
    x = rec.get("x_stage2")
    if isinstance(x, dict):
        for part, keys in (("evidence_state", ("value", "source", "note")),
                           ("resolvability", ("value", "repeat_measurements", "missing", "note"))):
            sub = x.get(part)
            if not isinstance(sub, dict):
                errs.append(f"{where}: 'x_stage2.{part}' must be an object")
                continue
            for k in keys:
                if k in sub and not isinstance(sub[k], str):
                    errs.append(f"{where}: 'x_stage2.{part}.{k}' must be a string")
        r = x.get("resolvability")
        if isinstance(r, dict) and not (isinstance(r.get("variables"), list)
                                        and all(isinstance(v, str) for v in r["variables"])):
            errs.append(f"{where}: resolvability.variables must be a list of backticked names (strings)")
    return errs


def check_records(records):
    errors, seen = [], set()
    for i, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            errors.append(f"line {i}: a version must be a JSON object")
            continue
        vid = rec.get("version_id", f"<line {i}>")
        where = f"line {i} ({vid})"
        for f in SLE_CORE:
            if f not in rec:
                errors.append(f"{where}: missing SLE core field '{f}'")
        errors.extend(_type_errors(rec, where))
        if vid in seen:
            errors.append(f"{where}: duplicate version_id '{vid}'")
        parents = rec.get("parents", [])
        if not isinstance(parents, list):
            parents = []
        for p in parents:
            if p not in seen:
                errors.append(f"{where}: parent '{p}' is not an earlier version in this file")
        seen.add(vid if isinstance(vid, str) else repr(vid))

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
