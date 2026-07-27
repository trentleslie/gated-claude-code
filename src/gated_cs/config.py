from dataclasses import dataclass
@dataclass(frozen=True)
class Thresholds:
    k: int = 5
    row_cap: int = 20
    cardinality_cap: int = 50
    bin_min_count: int = 5
    cadence_sample_rows: int = 200_000
    diurnal_block_hours: int = 4      # R13: coarsen activity-by-hour into 4h blocks
    # --- SDC residual-risk hardening (small per-person tables at the release gate) ---
    near_unique_ratio: float = 0.9    # non-numeric column with nunique/n above this is
                                      # identifier-like (shared by profiler.is_sensitive)
    max_quasi_identifier_cols: int = 1  # more than this many co-occurring quasi-identifier
                                        # columns in a count-less table -> quarantine (R3)
DEFAULTS = Thresholds()
