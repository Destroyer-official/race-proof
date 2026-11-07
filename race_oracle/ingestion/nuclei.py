"""Backward-compatibility shim for race_oracle.ingestion.nuclei -> race_proof.ingestion.nuclei."""
from race_proof.ingestion.nuclei import *
import race_proof.ingestion.nuclei as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
