import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT / "provision" / "skills" / "hypothesize"
SKILL = SKILL_DIR / "SKILL.md"
FIX = Path(__file__).resolve().parent / "fixtures" / "hypothesize"

SLE_CORE = ("version_id", "parents", "episode", "claim", "plan", "alternatives",
            "evidence", "critic_score", "critique", "selected")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SKILL_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check_record = _load("check_record")
find_vars = _load("find_vars")


def good():
    return [json.loads(ln) for ln in (FIX / "good.jsonl").read_text().splitlines() if ln.strip()]


def errors_for(records):
    return check_record.check_records(records)


# ---- check_record: happy path -------------------------------------------------
def test_good_lineage_passes():
    assert errors_for(good()) == []


def test_cli_exit_codes(tmp_path):
    ok = subprocess.run([sys.executable, str(SKILL_DIR / "check_record.py"), str(FIX / "good.jsonl")],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = good()
    del bad[0]["claim"]
    p = tmp_path / "bad.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in bad))
    res = subprocess.run([sys.executable, str(SKILL_DIR / "check_record.py"), str(p)],
                         capture_output=True, text=True)
    assert res.returncode != 0 and "claim" in (res.stdout + res.stderr)


# ---- check_record: structure ----------------------------------------------------
def test_missing_core_field_named():
    recs = good()
    del recs[0]["claim"]
    errs = errors_for(recs)
    assert any("claim" in e for e in errs)


def test_bad_evidence_state_value():
    recs = good()
    recs[0]["x_stage2"]["evidence_state"]["value"] = "likely"
    assert any("evidence_state" in e for e in errors_for(recs))


def test_space_form_resolvability_rejected():
    recs = good()
    recs[1]["x_stage2"]["resolvability"]["value"] = "not resolvable"
    assert any("resolvability" in e for e in errors_for(recs))


def test_parent_must_exist_earlier():
    recs = good()
    recs[0]["parents"] = ["cer-v2"]          # refers to a later line
    assert any("parent" in e for e in errors_for(recs))
    recs = good()
    recs[1]["parents"] = ["nope"]
    assert any("parent" in e for e in errors_for(recs))


def test_duplicate_version_id():
    recs = good()
    recs[1]["version_id"] = "cer-v1"
    recs[1]["parents"] = []
    assert any("duplicate" in e for e in errors_for(recs))


def test_undetermined_requires_missing():
    recs = good()
    recs[0]["x_stage2"]["resolvability"]["missing"] = ""
    assert any("missing" in e for e in errors_for(recs))


# ---- check_record: no restated numbers ------------------------------------------
def _with_evidence(text):
    recs = good()
    recs[0]["evidence"] = text
    return errors_for(recs)


def test_restated_numbers_flagged():
    assert _with_evidence("HR was 1.34 in 412 participants")


def test_stage_number_flagged():
    assert _with_evidence("Fails at stage 3 of follow-up")


def test_unquoted_lipid_name_flagged_backticked_passes():
    assert _with_evidence("Cer(d18:1/16:0) was higher")
    assert not _with_evidence("`Cer(d18:1/16:0)` was higher")


def test_letter_attached_and_citations_exempt():
    assert not _with_evidence("HbA1c and T2D confound; see PMC7806657, PMID:34555371, doi:10.1093/ageing/afac136, "
                              "https://paperclip.gxl.ai/evidence/r/NKELhoKDvYGlt8k8 and "
                              "results/abc123_ceramide__summary.csv")


def test_numbers_in_resolvability_note_flagged():
    recs = good()
    recs[1]["x_stage2"]["resolvability"]["note"] = "found 37 species"
    assert errors_for(recs)


# ---- find_vars ---------------------------------------------------------------------
DICT = json.loads((FIX / "dictionary.json").read_text())


def test_finds_both_name_variants_without_duplicates():
    hits = find_vars.find(DICT, ["Cer(d18:1/16:0)", "ceramide (d18:1/24:0)"])
    cols = sorted((h["file"], h["column"]) for h in hits)
    assert cols == [("lipids_panel.tsv", "ceramide (d18:1/24:0)"),
                    ("metabolomics_corrected.tsv", "Cer(d18:1/16:0)")]


def test_no_match_is_empty():
    assert find_vars.find(DICT, ["sphingosine-1-phosphate"]) == []


def test_output_keys_are_value_free():
    for h in find_vars.find(DICT, ["cer", "gait"]):
        assert set(h) <= {"file", "column", "dtype", "longitudinal", "cadence"}
        assert "histogram" not in json.dumps(h) and "0.12" not in json.dumps(h)


def test_longitudinal_states():
    by_col = {h["column"]: h for h in find_vars.find(DICT, ["cer", "gait"])}
    assert by_col["Cer(d18:1/16:0)"]["longitudinal"] == "present"
    assert by_col["ceramide (d18:1/24:0)"]["longitudinal"] == "present"      # temporal_coverage only
    assert by_col["ceramide (d18:1/24:0)"]["cadence"] == "annual"
    assert by_col["gait_speed"]["longitudinal"] == "absent"                 # date column, no facet
    assert by_col["Cer(d18:1/18:0)"]["longitudinal"] == "no_date_column"    # derived layer, no subject_key


def test_find_vars_cli():
    res = subprocess.run([sys.executable, str(SKILL_DIR / "find_vars.py"), str(FIX / "dictionary.json"), "gait"],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    rows = [json.loads(ln) for ln in res.stdout.splitlines() if ln.strip()]
    assert rows == [{"file": "frailty_survey.tsv", "column": "gait_speed", "dtype": "float64",
                     "longitudinal": "absent"}]


# ---- SKILL.md (the brief) ------------------------------------------------------------
def _skill():
    return SKILL.read_text()


def test_frontmatter():
    text = _skill()
    head = text[: text.index("\n---", 3)]
    assert "name: hypothesize" in head
    assert "description:" in head and "/hypothesize" in head


def test_governance_before_workflow():
    text = _skill().lower()
    g, w = text.index("## governance"), text.index("## workflow")
    assert g < w
    gov = text[g:w]
    for word in ("dictionary", "synthetic", "gate", "human review", "never restate"):
        assert word in gov, word


def test_fields_and_helpers_documented():
    text = _skill() + (SKILL_DIR / "references" / "hypothesis-record.md").read_text()
    for f in SLE_CORE + ("x_stage2", "evidence_state", "resolvability", "undetermined"):
        assert f in text, f
    sk = _skill()
    assert "python3 ~/.claude/skills/hypothesize/check_record.py" in sk
    assert "python3 ~/.claude/skills/hypothesize/find_vars.py ~/analysis/dictionary.json" in sk
    assert "docs/hypotheses/" in sk and "mkdir -p docs/hypotheses" in sk


def test_no_gated_submission_in_this_stage():
    assert "submit-analysis" not in _skill()


def test_no_readme_in_skill_dir():
    assert not (SKILL_DIR / "README.md").exists()      # deploy-skills excludes README.md


def test_reference_example_passes_checker():
    ref = (SKILL_DIR / "references" / "hypothesis-record.md").read_text()
    block = ref.split("```json", 1)[1].split("```", 1)[0]
    assert errors_for([json.loads(block)]) == []
