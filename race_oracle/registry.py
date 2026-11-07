"""Backward-compatibility shim for race_oracle.registry -> race_proof.registry."""
from race_proof.registry import *
import race_proof.registry as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
