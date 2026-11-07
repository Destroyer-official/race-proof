"""Backward-compatibility shim for race_oracle.evidence.packager -> race_proof.evidence.packager."""
from race_proof.evidence.packager import *
import race_proof.evidence.packager as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
