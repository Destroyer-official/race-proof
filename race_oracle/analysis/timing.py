"""Backward-compatibility shim for race_oracle.analysis.timing -> race_proof.analysis.timing."""
from race_proof.analysis.timing import *
import race_proof.analysis.timing as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
