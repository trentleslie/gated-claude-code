from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "provision" / "skills"

def frontmatter_keys(path: Path) -> set[str]:
    text = path.read_text()
    assert text.startswith("---"), f"{path}: missing frontmatter opener"
    end = text.index("\n---", 3)
    body = text[3:end]
    return {ln.split(":", 1)[0].strip() for ln in body.splitlines() if ":" in ln}

def test_skills_dir_exists():
    assert SKILLS_DIR.is_dir(), f"{SKILLS_DIR} not found"

def test_every_skill_has_valid_frontmatter():
    skills = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    assert skills, "no SKILL.md files found under provision/skills/"
    for s in skills:
        keys = frontmatter_keys(s)
        assert "name" in keys, f"{s}: frontmatter missing name"
        assert "description" in keys, f"{s}: frontmatter missing description"
