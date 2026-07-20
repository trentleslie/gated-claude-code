import json, py_compile
from pathlib import Path

TRE = Path(__file__).resolve().parents[2] / "provision" / "skills" / "tre-runpack"
HEADER = "feature,beta,se,n,metric,platform"

def test_ukb_template_compiles(tmp_path):
    src = TRE / "templates" / "ukb_rap_template.py"
    py_compile.compile(str(src), cfile=str(tmp_path / "out.pyc"), doraise=True)

def test_ukb_template_contract():
    text = (TRE / "templates" / "ukb_rap_template.py").read_text()
    assert "tre_aggregates.csv" in text
    assert HEADER.replace(",", '", "') in text or HEADER in text
    assert "MIN_CELL" in text
    assert "{{" in text  # has fill tokens

def test_aou_notebook_is_valid_json():
    nb = json.loads((TRE / "templates" / "all_of_us_template.ipynb").read_text())
    assert nb.get("nbformat") == 4
    assert isinstance(nb.get("cells"), list) and nb["cells"]

def test_aou_notebook_contract():
    nb = json.loads((TRE / "templates" / "all_of_us_template.ipynb").read_text())
    src = "\n".join("".join(c.get("source", [])) for c in nb["cells"])
    assert "MIN_CELL = 21" in src, "All of Us pack must enforce the >=21 small-cell rule"
    assert "tre_aggregates.csv" in src
    assert HEADER in src or HEADER.replace(",", '", "') in src
