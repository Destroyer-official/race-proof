"""Backward-compatibility shim for race_oracle.agent.guard -> race_proof.agent.guard."""
from race_proof.agent.guard import *
import race_proof.agent.guard as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
