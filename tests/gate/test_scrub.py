from gated_cs.gate.scrub import scrub


def test_scrub_redacts_values_keeps_shape():
    tb = 'ValueError: bad row 42.7 for user7@example.com in file.py:12'
    out = scrub(tb)
    assert "user7@example.com" not in out
    assert "42.7" not in out
    assert "ValueError" in out and "file.py:12" in out


def test_scrub_redacts_single_quoted_value():
    out = scrub("KeyError: 'Jane Doe'")
    assert "Jane Doe" not in out
    assert "KeyError" in out and "<redacted>" in out


def test_scrub_redacts_double_quoted_value():
    out = scrub('ValueError: bad category "Stage IV Cancer"')
    assert "Stage IV Cancer" not in out
    assert "ValueError" in out


def test_scrub_keeps_line_reference_with_quotes_present():
    out = scrub("KeyError: 'Jane Doe' at file.py:12")
    assert "file.py:12" in out and "Jane Doe" not in out
