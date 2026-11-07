"""Backward-compatibility shim for race_oracle.ingestion.burp_xml -> race_proof.ingestion.burp_xml."""
from race_proof.ingestion.burp_xml import *
import race_proof.ingestion.burp_xml as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
