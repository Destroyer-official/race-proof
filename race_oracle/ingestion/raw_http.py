"""Backward-compatibility shim for race_oracle.ingestion.raw_http -> race_proof.ingestion.raw_http."""
from race_proof.ingestion.raw_http import *
import race_proof.ingestion.raw_http as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
