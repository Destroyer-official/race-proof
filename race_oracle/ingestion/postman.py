"""Backward-compatibility shim for race_oracle.ingestion.postman -> race_proof.ingestion.postman."""
from race_proof.ingestion.postman import *
import race_proof.ingestion.postman as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
