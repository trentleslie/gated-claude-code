#!/usr/bin/env python3
"""Find Arivale dictionary variables by name, without exposing any values.

Stdlib only. Usage:
  python3 find_vars.py ~/analysis/dictionary.json "Cer(d18:1/16:0)" "ceramide (d18:1/16:0)" ...
Patterns are case-insensitive substrings (not regexes, so lipid names need no escaping).

Prints one JSON object per match: file, column, dtype, and a longitudinal signal for the file:
  present         a date-like column carries temporal_distribution or temporal_coverage (cadence shown)
  absent          date-like columns exist but carry neither facet
  no_date_column  the file has no date-like column
Never prints histograms, counts, month ranges or category values. A missing facet can be a profiler
limitation, so 'absent' or 'no_date_column' means resolvability 'undetermined', never 'not_resolvable'.
"""
import json
import re
import sys

# Mirrors gated_cs.profiler.temporal._DATETIME_NAME.
_DATETIME_NAME = re.compile(r"date|time|timestamp|_at$", re.I)


def _longitudinal(columns):
    dated = {n: c for n, c in columns.items() if _DATETIME_NAME.search(n)}
    dated.update({n: c for n, c in columns.items()
                  if isinstance(c, dict) and (c.get("temporal_distribution") or c.get("temporal_coverage"))})
    if not dated:
        return "no_date_column", None
    for c in dated.values():
        if not isinstance(c, dict):
            continue
        facet = c.get("temporal_distribution") or c.get("temporal_coverage")
        if facet:
            # prefer coverage cadence (whole-file shape); fall back to distribution cadence
            cad = (c.get("temporal_coverage") or {}).get("cadence") or (c.get("temporal_distribution") or {}).get("cadence")
            return "present", cad
    return "absent", None


def find(dictionary, patterns):
    pats = [p.lower() for p in patterns]
    hits = []
    for fname, prof in (dictionary.get("files") or {}).items():
        columns = (prof or {}).get("columns") or {}
        state, cadence = _longitudinal(columns)
        for col, facts in columns.items():
            if any(p in col.lower() for p in pats):
                row = {"file": fname, "column": col,
                       "dtype": (facts or {}).get("dtype") if isinstance(facts, dict) else None,
                       "longitudinal": state}
                if state == "present" and cadence:
                    row["cadence"] = cadence
                hits.append(row)
    return hits


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        print("usage: find_vars.py <dictionary.json> <pattern> [pattern ...]", file=sys.stderr)
        return 2
    with open(argv[0]) as fh:
        d = json.load(fh)
    for row in find(d, argv[1:]):
        print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
