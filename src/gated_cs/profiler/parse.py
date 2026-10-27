import csv, re
import pandas as pd
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

PARQUET_EXTS = (".parquet", ".pq")

def is_parquet(path: str) -> bool:
    return path.lower().endswith(PARQUET_EXTS)

def read_table(path: str):
    """Return (ParsedFile, DataFrame) for a delimited text or parquet file.

    Parquet is self-describing, so it has no delimiter, comment metadata or
    header offset; column names are coerced to str to match the text path."""
    if is_parquet(path):
        # imported here so csv/tsv profiling still works on a host whose venv predates pyarrow
        import pyarrow as pa
        import pyarrow.parquet as pq
        nested = [f.name for f in pq.read_schema(path) if pa.types.is_nested(f.type)]
        if nested:
            raise ValueError(f"{path}: nested (list/struct/map) parquet columns are not "
                             f"supported, flatten them first: {', '.join(nested)}")
        df = pd.read_parquet(path)
        df.columns = [str(c) for c in df.columns]
        return ParsedFile(delimiter=None, header=list(df.columns)), df
    parsed = parse_file(path)
    header_line = max(parsed.data_start_line - 1, 0)
    df = pd.read_csv(path, sep=parsed.delimiter, skiprows=header_line,
                     header=0, low_memory=False)
    return parsed, df
