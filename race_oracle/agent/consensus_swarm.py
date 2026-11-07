"""Backward-compatibility shim for race_oracle.agent.consensus_swarm -> race_proof.agent.consensus_swarm."""
from race_proof.agent.consensus_swarm import *
import race_proof.agent.consensus_swarm as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
