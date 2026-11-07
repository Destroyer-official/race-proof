"""Backward-compatibility shim for race_oracle.analysis.multi_endpoint -> race_proof.analysis.multi_endpoint."""
from race_proof.analysis.multi_endpoint import *
import race_proof.analysis.multi_endpoint as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
