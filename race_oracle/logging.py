"""Backward-compatibility shim for race_oracle.logging -> race_proof.logging."""
from race_proof.logging import *
import race_proof.logging as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
