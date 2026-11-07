"""Backward-compatibility shim for race_oracle.evidence.sarif -> race_proof.evidence.sarif."""
from race_proof.evidence.sarif import *
import race_proof.evidence.sarif as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
