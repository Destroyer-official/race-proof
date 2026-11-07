"""Backward-compatibility shim for race_oracle.evidence.attestation -> race_proof.evidence.attestation."""
from race_proof.evidence.attestation import *
import race_proof.evidence.attestation as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
