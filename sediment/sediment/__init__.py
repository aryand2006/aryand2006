"""sediment -- a deterministic structural-erosion gate for machine-authored code.

Measures the structural debt a change *adds*, rather than the absolute state of
the code it lands in, so it is usable on any codebase from the first commit.
"""

__version__ = "0.1.0"

from .analyze import Snapshot, snapshot_at_path, snapshot_at_ref
from .metrics import Unit, analyze_source
from .score import ErosionReport, compare
from .slop import Finding, analyze_slop

__all__ = [
    "Snapshot",
    "Unit",
    "Finding",
    "ErosionReport",
    "analyze_source",
    "analyze_slop",
    "compare",
    "snapshot_at_path",
    "snapshot_at_ref",
    "__version__",
]
