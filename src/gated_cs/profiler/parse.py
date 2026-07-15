import csv, re
from dataclasses import dataclass, field

@dataclass
class ParsedFile:
    delimiter: str
    file_metadata: list = field(default_factory=list)
    column_descriptions: dict = field(default_factory=dict)
    header: list = field(default_factory=list)
    data_start_line: int = 0

_COL_DESC = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*:\s*(.+?)\s*$")

def _detect_delimiter(path):
    if path.endswith(".tsv"):
        return "\t"
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            return "\t" if line.count("\t") > line.count(",") else ","
    return ","

def parse_file(path: str) -> ParsedFile:
    delim = _detect_delimiter(path)
    meta, descs = [], {}
    header, data_start = [], 0
    with open(path) as f:
        for i, line in enumerate(f):
            if line.startswith("#"):
                body = line[1:].strip()
                meta.append(body)
                m = _COL_DESC.match(body)
                if m:
                    descs[m.group(1)] = m.group(2)
                continue
            if not line.strip():
                continue
            header = next(csv.reader([line], delimiter=delim))
            data_start = i + 1
            break
    # keep only descriptions that name an actual column
    descs = {k: v for k, v in descs.items() if k in header}
    return ParsedFile(delim, meta, descs, header, data_start)
