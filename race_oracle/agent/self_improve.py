"""Backward-compatibility shim for race_oracle.agent.self_improve -> race_proof.agent.self_improve."""
from race_proof.agent.self_improve import *
import race_proof.agent.self_improve as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
