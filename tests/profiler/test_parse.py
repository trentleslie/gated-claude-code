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

def test_non_column_descriptions_filtered_from_tsv():
    """Non-column descriptions are filtered: only descriptions for actual columns are kept."""
    p = parse_file(str(FX / "tabbed.tsv"))
    # tabbed.tsv has "# glucose: ..." but no "# site: ...", so site should not be in column_descriptions
    assert "site" not in p.column_descriptions
    assert "glucose" in p.column_descriptions

def test_non_column_descriptions_filtered_with_bogus():
    """Column descriptions for non-existent columns are excluded."""
    content = "# realcol: a real one\n# bogus: not a column\nrealcol,other\n1,2\n"
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(content)
        f.flush()
        p = parse_file(f.name)
        assert p.column_descriptions == {"realcol": "a real one"}
        assert "bogus" not in p.column_descriptions
        import os
        os.unlink(f.name)

def test_data_start_line_for_simple_csv():
    """data_start_line points to the first data row after the header."""
    p = parse_file(str(FX / "simple.csv"))
    # simple.csv has 3 comment lines (indices 0-2), header at index 3, so data_start_line == 4
    assert p.data_start_line == 4

def test_blank_lines_before_header_are_skipped():
    """Blank lines between comments and header are skipped; header and descriptions are still parsed."""
    content = "# c: desc\n\n\nc,d\n5,6\n"
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(content)
        f.flush()
        p = parse_file(f.name)
        assert p.header == ["c", "d"]
        assert p.column_descriptions == {"c": "desc"}
        import os
        os.unlink(f.name)

def test_no_header_comments_only_file():
    """File with only comments and no header leaves header empty and data_start_line at 0."""
    content = "# just a comment\n# another\n"
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write(content)
        f.flush()
        p = parse_file(f.name)
        assert p.header == []
        assert p.data_start_line == 0
        import os
        os.unlink(f.name)
