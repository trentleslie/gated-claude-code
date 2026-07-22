from dataclasses import dataclass
@dataclass(frozen=True)
class Thresholds:
    k: int = 5
    row_cap: int = 20
    cardinality_cap: int = 50
    bin_min_count: int = 5
    cadence_sample_rows: int = 200_000
    diurnal_block_hours: int = 4      # R13: coarsen activity-by-hour into 4h blocks
DEFAULTS = Thresholds()
