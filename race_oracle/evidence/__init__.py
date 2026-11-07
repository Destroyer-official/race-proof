"""Backward-compatibility shim for race_oracle.evidence -> race_proof.evidence."""
from race_proof.evidence import *
import race_proof.evidence as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
