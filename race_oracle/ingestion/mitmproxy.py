"""Backward-compatibility shim for race_oracle.ingestion.mitmproxy -> race_proof.ingestion.mitmproxy."""
from race_proof.ingestion.mitmproxy import *
import race_proof.ingestion.mitmproxy as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
