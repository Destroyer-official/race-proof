"""Backward-compatibility shim for race_oracle.analysis.happens_before -> race_proof.analysis.happens_before."""
from race_proof.analysis.happens_before import *
import race_proof.analysis.happens_before as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
