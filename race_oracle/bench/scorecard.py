"""Backward-compatibility shim for race_oracle.bench.scorecard -> race_proof.bench.scorecard."""
from race_proof.bench.scorecard import *
import race_proof.bench.scorecard as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
