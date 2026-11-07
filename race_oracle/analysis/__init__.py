"""Backward-compatibility shim for race_oracle.analysis -> race_proof.analysis."""
from race_proof.analysis import *
import race_proof.analysis as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
