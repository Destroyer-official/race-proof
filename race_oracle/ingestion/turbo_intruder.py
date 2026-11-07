"""Backward-compatibility shim for race_oracle.ingestion.turbo_intruder -> race_proof.ingestion.turbo_intruder."""
from race_proof.ingestion.turbo_intruder import *
import race_proof.ingestion.turbo_intruder as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
