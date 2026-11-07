"""Backward-compatibility shim for race_oracle.evidence.poc_generator -> race_proof.evidence.poc_generator."""
from race_proof.evidence.poc_generator import *
import race_proof.evidence.poc_generator as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
