"""Backward-compatibility shim for race_oracle.formal.tla_generator -> race_proof.formal.tla_generator."""
from race_proof.formal.tla_generator import *
import race_proof.formal.tla_generator as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
