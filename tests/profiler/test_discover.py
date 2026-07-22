import os
from gated_cs.profiler.discover import discover_files, DiscoveredFile

def _touch(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("x")

def test_discover_walks_devices_excludes_checkpoints_and_tags(tmp_path):
    base = str(tmp_path)
    _touch(os.path.join(base, "oura_ring", "TIME_oura_daily_sleep_20260610.csv"))
    _touch(os.path.join(base, "stelo_cgm", "processed", "TIME_cgm_all_subjects.csv"))
    _touch(os.path.join(base, "redcap_questionnaires", "raw", "TIME_redcap_questions.csv"))
    _touch(os.path.join(base, "redcap_questionnaires", "raw", "TIME_redcap_response_options.csv"))
    _touch(os.path.join(base, "redcap_questionnaires", "raw", "TIME_redcap_responses_long.csv"))
    _touch(os.path.join(base, "stelo_cgm", "processed", ".ipynb_checkpoints",
                        "TIME_cgm_all_subjects-checkpoint.csv"))
    _touch(os.path.join(base, "oura_ring", "notes.txt"))  # non-csv ignored

    found = discover_files(base)
    rels = [f.relpath for f in found]

    assert not any(".ipynb_checkpoints" in r for r in rels)
    assert not any(r.endswith("notes.txt") for r in rels)
    assert len(found) == 5
    by_rel = {f.relpath: f for f in found}
    sleep = by_rel[os.path.join("oura_ring", "TIME_oura_daily_sleep_20260610.csv")]
    assert sleep.source == "oura_ring" and sleep.stage == "" and sleep.role == "data"
    cgm = by_rel[os.path.join("stelo_cgm", "processed", "TIME_cgm_all_subjects.csv")]
    assert cgm.source == "stelo_cgm" and cgm.stage == "processed" and cgm.role == "data"
    q = by_rel[os.path.join("redcap_questionnaires", "raw", "TIME_redcap_questions.csv")]
    assert q.stage == "raw" and q.role == "codebook"
    opts = by_rel[os.path.join("redcap_questionnaires", "raw", "TIME_redcap_response_options.csv")]
    assert opts.role == "codebook"
    long = by_rel[os.path.join("redcap_questionnaires", "raw", "TIME_redcap_responses_long.csv")]
    assert long.role == "data"  # raw but not a codebook stem
    assert rels == sorted(rels)  # sorted output
