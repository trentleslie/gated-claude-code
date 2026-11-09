#!/usr/bin/env python3
"""Find Arivale dictionary variables by name, without exposing any values.

Stdlib only. Usage:
  python3 find_vars.py ~/analysis/dictionary.json "Cer(d18:1/16:0)" "ceramide (d18:1/16:0)" ...
Patterns are case-insensitive substrings (not regexes, so lipid names need no escaping).

Prints one JSON object per match: file, column, dtype, and a longitudinal signal for the file:
  present         a date-like column carries temporal_distribution, which the profiler emits only when
                  participants have repeat events (single-event guard); cadence shown
  unknown         date-like columns exist without temporal_distribution. temporal_coverage alone does
                  NOT show repeats: it is emitted even when every participant has a single draw
  no_date_column  the file has no date-like column
Never prints histograms, counts, month ranges or category values. Only 'present' supports
repeat_measurements 'present'; 'unknown' or 'no_date_column' means resolvability 'undetermined' for a
longitudinal claim, never 'not_resolvable'.
"""
import json
import re
import sys

# Mirrors gated_cs.profiler.temporal._DATETIME_NAME.
_DATETIME_NAME = re.compile(r"date|time|timestamp|_at$", re.I)


def _longitudinal(columns):
    dated = {n: c for n, c in columns.items()
             if _DATETIME_NAME.search(n)
             or (isinstance(c, dict) and (c.get("temporal_distribution") or c.get("temporal_coverage")))}
    if not dated:
        return "no_date_column", None
    for c in dated.values():
        td = c.get("temporal_distribution") if isinstance(c, dict) else None
        if td:
            return "present", (td or {}).get("cadence")
    return "unknown", None


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
