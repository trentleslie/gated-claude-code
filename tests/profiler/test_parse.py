import pathlib
from gated_cs.profiler.parse import parse_file
FX = pathlib.Path(__file__).parent.parent / "fixtures"

def test_parse_csv_captures_metadata_and_header():
    p = parse_file(str(FX / "simple.csv"))
    assert p.delimiter == ","
    assert p.header == ["age", "sex"]
    assert p.column_descriptions["age"] == "age in years"
    assert p.column_descriptions["sex"] == "biological sex (M/F)"
    assert "source: arivale_snapshot_2018" in p.file_metadata

def test_parse_tsv_detects_tab():
    p = parse_file(str(FX / "tabbed.tsv"))
    assert p.delimiter == "\t"
    assert p.header == ["glucose", "site"]
