from gated_cs.config import DEFAULTS
from gated_cs.profiler.profile import _nice_edges

def test_nice_edges_locks_current_behavior():
    edges = _nice_edges(40.0, 180.0, DEFAULTS)
    assert edges == [40.0, 60.0, 80.0, 100.0, 120.0, 140.0, 160.0, 180.0, 200.0]
