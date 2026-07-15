import pathlib
from gated_cs.profiler.profile import profile_file
from gated_cs.profiler.synthesize import synthesize

FX = pathlib.Path(__file__).parent.parent / "fixtures"


def test_synthetic_shape_and_columns():
    prof = profile_file(str(FX / "simple.csv"))
    df = synthesize(prof, n_rows=50, seed=1)
    assert list(df.columns) == ["age", "sex"]
    assert len(df) == 50
    assert set(df["sex"].unique()) <= {"M", "F"}


def test_sensitive_column_is_placeholder():
    prof = profile_file(str(FX / "with_ids.csv"))
    df = synthesize(prof, n_rows=10)
    assert (df["email"] == "<suppressed>").all()
