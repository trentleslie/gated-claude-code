from gated_cs.gate.scrub import scrub


def test_scrub_redacts_values_keeps_shape():
    tb = 'ValueError: bad row 42.7 for user7@example.com in file.py:12'
    out = scrub(tb)
    assert "user7@example.com" not in out
    assert "42.7" not in out
    assert "ValueError" in out and "file.py:12" in out
