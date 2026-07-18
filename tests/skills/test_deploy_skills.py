import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "provision" / "bin" / "deploy-skills"

def _run(dest: Path):
    return subprocess.run([str(DEPLOY), "--dest", str(dest)],
                          capture_output=True, text=True, check=True).stdout

def test_deploy_is_idempotent(tmp_path):
    first = _run(tmp_path / "skills")
    second = _run(tmp_path / "skills")
    # rsync -i marks sent files with a leading '>f'; a clean second run sends nothing.
    assert any(line.startswith(">f") for line in first.splitlines()), "first run copied nothing"
    assert not any(line.startswith(">f") for line in second.splitlines()), \
        f"second run not idempotent:\n{second}"

def test_deployed_tree_matches_source(tmp_path):
    dest = tmp_path / "skills"
    _run(dest)
    assert (dest / "replicate" / "SKILL.md").is_file()
