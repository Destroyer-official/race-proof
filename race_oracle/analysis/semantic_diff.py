"""Backward-compatibility shim for race_oracle.analysis.semantic_diff -> race_proof.analysis.semantic_diff."""
from race_proof.analysis.semantic_diff import *
import race_proof.analysis.semantic_diff as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
