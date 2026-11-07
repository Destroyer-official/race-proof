"""Backward-compatibility shim for race_oracle.exceptions -> race_proof.exceptions."""
from race_proof.exceptions import *
import race_proof.exceptions as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
