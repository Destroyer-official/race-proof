"""Backward-compatibility shim for race_oracle.analysis.anomaly_classifier -> race_proof.analysis.anomaly_classifier."""
from race_proof.analysis.anomaly_classifier import *
import race_proof.analysis.anomaly_classifier as _orig

if hasattr(_orig, "__all__"):
    __all__ = list(_orig.__all__)
