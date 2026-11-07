"""Backward-compatibility shim for race_oracle.analysis.statistics -> race_proof.analysis.statistics."""
from race_proof.analysis.statistics import *
import race_proof.analysis.statistics as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
