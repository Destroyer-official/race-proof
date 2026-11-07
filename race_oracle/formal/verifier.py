"""Backward-compatibility shim for race_oracle.formal.verifier -> race_proof.formal.verifier."""
from race_proof.formal.verifier import *
import race_proof.formal.verifier as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
