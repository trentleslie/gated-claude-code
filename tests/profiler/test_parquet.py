import json, os, shutil
import pandas as pd
from gated_cs.profiler.build_dictionary import build, build_synthetic_from_dictionary
from gated_cs.profiler.discover import discover_files
from gated_cs.profiler.profile import profile_file

REAL_IDS = [f"P{s:03d}" for s in range(12)]


def _labs(n_per=6):
    rows = [{"participant_id": pid,
             "visit": pd.Timestamp("2024-03-01") + pd.Timedelta(days=30 * v),
             "glucose": 80.0 + (s * 3 + v) % 40,
             "n_meds": (s + v) % 4,
             "fasting": bool((s + v) % 2),
             "site": ["north", "south"][s % 2]}
            for s, pid in enumerate(REAL_IDS) for v in range(n_per)]
    df = pd.DataFrame(rows)
    df["site"] = df["site"].astype("category")
    return df


def _mixed_dir(tmp_path):
    base = tmp_path / "data"
    (base / "clinic").mkdir(parents=True)
    _labs().to_parquet(base / "clinic" / "labs.parquet", index=False)
    pd.DataFrame({"participant_id": REAL_IDS, "age": [30 + i for i in range(12)]}
                 ).to_csv(base / "clinic" / "demo.csv", index=False)
    return base


def test_discover_includes_parquet(tmp_path):
    base = _mixed_dir(tmp_path)
    rels = {f.relpath for f in discover_files(str(base))}
    assert rels == {os.path.join("clinic", "labs.parquet"), os.path.join("clinic", "demo.csv")}


def test_profile_parquet(tmp_path):
    base = _mixed_dir(tmp_path)
    prof = profile_file(str(base / "clinic" / "labs.parquet"))
    assert prof["row_count"] == 72
    assert prof["subject_key"] == "participant_id" and prof["cohort_n"] == 12
    assert set(prof["columns"]) == {"participant_id", "visit", "glucose", "n_meds", "fasting", "site"}
    assert prof["columns"]["glucose"]["histogram"]
    assert prof["columns"]["site"]["categories"] == ["north", "south"]
    # native datetime64 column: profiled as temporal, never as raw-date categories
    assert prof["columns"]["visit"]["sensitive"] is True
    assert "temporal_coverage" in prof["columns"]["visit"]


def test_build_writes_parquet_synthetic_with_native_dtypes(tmp_path):
    base = _mixed_dir(tmp_path)
    out = tmp_path / "out"
    d = build(str(base), str(out))
    rel = os.path.join("clinic", "labs.parquet")
    assert rel in d["files"]
    syn = pd.read_parquet(out / "synthetic_samples" / rel)
    assert list(syn.columns) == ["participant_id", "visit", "glucose", "n_meds", "fasting", "site"]
    assert pd.api.types.is_datetime64_any_dtype(syn["visit"])
    assert pd.api.types.is_integer_dtype(syn["n_meds"])
    assert pd.api.types.is_float_dtype(syn["glucose"])
    assert pd.api.types.is_bool_dtype(syn["fasting"])
    assert isinstance(syn["site"].dtype, pd.CategoricalDtype)
    # join keys come from the shared SYNTH_ pool, so parquet joins to the csv synthetic
    demo = pd.read_csv(out / "synthetic_samples" / "clinic" / "demo.csv")
    assert syn["participant_id"].str.startswith("SYNTH_").all()
    assert len(syn.merge(demo, on="participant_id")) > 0


def test_parquet_no_raw_values_leak(tmp_path):
    base = _mixed_dir(tmp_path)
    out = tmp_path / "out"
    build(str(base), str(out))
    dict_text = (out / "dictionary.json").read_text() + (out / "dictionary.md").read_text()
    syn = pd.read_parquet(out / "synthetic_samples" / "clinic" / "labs.parquet")
    for pid in REAL_IDS:
        assert pid not in dict_text and pid not in syn.astype(str).to_csv()
    # synthetic dates are drawn inside the coverage window, so a coincidental day match
    # there is not a leak; the dictionary itself must carry no exact dates
    for v in range(6):
        day = (pd.Timestamp("2024-03-01") + pd.Timedelta(days=30 * v)).strftime("%Y-%m-%d")
        assert day not in dict_text


def test_build_synthetic_from_dictionary_regenerates_parquet(tmp_path):
    base = _mixed_dir(tmp_path)
    out = tmp_path / "out"
    build(str(base), str(out))
    shutil.rmtree(out / "synthetic_samples")
    n = build_synthetic_from_dictionary(str(out / "dictionary.json"), str(out))
    assert n == 2
    syn = pd.read_parquet(out / "synthetic_samples" / "clinic" / "labs.parquet")
    assert len(syn) == 100 and pd.api.types.is_datetime64_any_dtype(syn["visit"])


def test_parquet_codebook_text(tmp_path):
    base = tmp_path / "data"
    (base / "survey" / "raw").mkdir(parents=True)
    pd.DataFrame({"field_name": ["q1", "q2"], "question": ["How tired?", "How stressed?"]}
                 ).to_parquet(base / "survey" / "raw" / "questions.parquet", index=False)
    out = tmp_path / "out"
    d = build(str(base), str(out))
    prof = d["files"][os.path.join("survey", "raw", "questions.parquet")]
    assert prof["role"] == "codebook"
    assert prof["codebook_text"]["question"] == ["How stressed?", "How tired?"]
    assert not (out / "synthetic_samples" / "survey").exists()


def test_parquet_constant_bool_and_tz_preserved(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    pd.DataFrame({"participant_id": REAL_IDS * 5,
                  "consented": [True] * 60,
                  "ts": pd.date_range("2024-01-01", periods=60, freq="D", tz="America/Los_Angeles")}
                 ).to_parquet(base / "x.parquet", index=False)
    out = tmp_path / "out"
    build(str(base), str(out))
    syn = pd.read_parquet(out / "synthetic_samples" / "x.parquet")
    assert str(syn["ts"].dt.tz) == "America/Los_Angeles"
    assert pd.api.types.is_bool_dtype(syn["consented"])


def test_restore_dtype_bool_labels():
    from gated_cs.profiler.build_dictionary import _restore_dtype
    out = _restore_dtype(pd.Series(["True", "False", "True"]), "bool")
    assert out.tolist() == [True, False, True] and out.dtype == bool


def test_nested_parquet_column_fails_clearly(tmp_path):
    import pytest
    base = tmp_path / "data"
    base.mkdir()
    pd.DataFrame({"participant_id": REAL_IDS[:5], "meds": [["a", "b"]] * 5}
                 ).to_parquet(base / "y.parquet", index=False)
    with pytest.raises(ValueError, match="nested.*meds"):
        build(str(base), str(tmp_path / "out"))


def test_restore_dtype_unknown_timezone_keeps_generated_values():
    from gated_cs.profiler.build_dictionary import _restore_dtype
    s = pd.Series(["2024-01-01 08:00:00", "2024-01-02 09:00:00"])
    # a dateutil tz renders as an unparseable zone name; the cast is best-effort, never a crash
    for dtype in ("datetime64[ns, tzfile('/usr/share/zoneinfo/US/Pacific')]",
                  "datetime64[ns, Not/AZone]"):
        assert _restore_dtype(s, dtype).tolist() == s.tolist()


def test_csv_profiling_works_without_pyarrow(tmp_path):
    import subprocess, sys
    pd.DataFrame({"participant_id": REAL_IDS, "age": range(12)}).to_csv(tmp_path / "d.csv", index=False)
    code = ("import sys; sys.modules['pyarrow'] = None; sys.modules['pyarrow.parquet'] = None\n"
            "from gated_cs.profiler.build_dictionary import build\n"
            f"build({str(tmp_path)!r}, {str(tmp_path / 'out')!r})\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": "src"})
    assert r.returncode == 0, r.stderr[-500:]
    assert (tmp_path / "out" / "synthetic_samples" / "d.csv").exists()
