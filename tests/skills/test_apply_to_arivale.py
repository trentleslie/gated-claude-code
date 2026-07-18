from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "provision" / "skills" / "apply-to-arivale" / "SKILL.md"

def test_frontmatter_trigger():
    text = SKILL.read_text()
    assert text.startswith("---")
    head = text[: text.index("\n---", 3)].lower()
    assert "name:" in head and "apply-to-arivale" in head
    assert "/apply-to-arivale" in text

def test_pipeline_stages_present():
    text = SKILL.read_text()
    for stage in ("S0", "S1", "S2", "S3", "S4", "S5"):
        assert stage in text, f"missing stage {stage}"

def test_extension_catalog_and_handoffs():
    text = SKILL.read_text().lower()
    for ext in ("longitudinal", "intervention", "cross-platform",
                "multi-omic", "microbiome mediation", "prs"):
        assert ext in text, f"extension '{ext}' not documented"
    assert "/validate" in text and "/tre-runpack" in text
    assert "method-kd-biological-age" in text        # reuse for aging-clock papers
    assert "submit-analysis" in text                 # gate discipline
