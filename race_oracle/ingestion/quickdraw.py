"""Backward-compatibility shim for race_oracle.ingestion.quickdraw -> race_proof.ingestion.quickdraw."""
from race_proof.ingestion.quickdraw import *
import race_proof.ingestion.quickdraw as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
