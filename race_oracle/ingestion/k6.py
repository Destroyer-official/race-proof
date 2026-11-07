"""Backward-compatibility shim for race_oracle.ingestion.k6 -> race_proof.ingestion.k6."""
from race_proof.ingestion.k6 import *
import race_proof.ingestion.k6 as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
