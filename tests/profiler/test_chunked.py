import numpy as np
import pandas as pd
from gated_cs.config import DEFAULTS
from gated_cs.profiler.profile import profile_file, profile_file_chunked

def _write(tmp_path):
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "subject_id": rng.integers(0, 30, size=5000).astype(str),
        "hr": rng.integers(40, 180, size=5000),
        "quality": rng.choice(["good", "fair", "poor"], size=5000),
    })
    p = tmp_path / "big.csv"
    df.to_csv(p, index=False)
    return str(p)

def test_chunked_matches_single_read(tmp_path):
    path = _write(tmp_path)
    single = profile_file(path, DEFAULTS)
    chunked = profile_file_chunked(path, DEFAULTS, chunk_rows=337)  # deliberately ragged
    assert single["row_count"] == chunked["row_count"] == 5000
    for col in ("hr", "quality"):
        assert chunked["columns"][col] == single["columns"][col], col
