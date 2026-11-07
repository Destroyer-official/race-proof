"""Backward-compatibility shim for race_oracle.ingestion.base -> race_proof.ingestion.base."""
from race_proof.ingestion.base import *
import race_proof.ingestion.base as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
