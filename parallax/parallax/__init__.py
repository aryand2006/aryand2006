"""parallax -- measure how much a backtest result depends on implementation choices.

The same strategy, on the same data, reports a different Sharpe depending on
decisions no paper reports and most libraries do not document: when a signal
fills, how commission is charged, whether shares are whole. This measures the
size of that dependence and attributes it to the decisions responsible.
"""

__version__ = "0.1.0"

from .data import Market, generate, load_csv
from .divergence import Divergence, amplification, attribute
from .engine import Result, run
from .spec import AXES, ExecutionSpec, enumerate_specs
from .sweep import Sweep, run_all, run_strategy

__all__ = [
    "AXES",
    "Divergence",
    "ExecutionSpec",
    "Market",
    "Result",
    "Sweep",
    "amplification",
    "attribute",
    "enumerate_specs",
    "generate",
    "load_csv",
    "run",
    "run_all",
    "run_strategy",
    "__version__",
]
