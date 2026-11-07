"""Backward-compatibility shim for race_oracle.analysis.invariants -> race_proof.analysis.invariants."""
from race_proof.analysis.invariants import *
import race_proof.analysis.invariants as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
