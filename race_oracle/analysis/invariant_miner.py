"""Backward-compatibility shim for race_oracle.analysis.invariant_miner -> race_proof.analysis.invariant_miner."""
from race_proof.analysis.invariant_miner import *
import race_proof.analysis.invariant_miner as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
