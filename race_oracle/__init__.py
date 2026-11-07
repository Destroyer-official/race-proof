"""Backward-compatibility shim package for race_oracle -> race_proof."""
import sys
import race_proof

sys.modules["race_oracle"] = race_proof

from race_proof.config import ProofConfig, OracleConfig, config
from race_proof.exceptions import (
    RaceProofError,
    IngestionError,
    VerificationError,
    FormalProofError,
    AgentSandboxError,
    AttestationError,
)
from race_proof.models import (
    AnalysisDimension,
    DimensionResult,
    InvariantOperator,
    InvariantRule,
    InvariantViolation,
    RaceRequest,
    RaceResponse,
    RaceSession,
    Verdict,
    VerdictLevel,
)
from race_proof.verdict import VerdictEngine

# Compatibility aliases
VerdictClass = VerdictLevel

__all__ = [
    "config",
    "ProofConfig",
    "OracleConfig",
    "VerdictEngine",
    "Verdict",
    "VerdictClass",
    "VerdictLevel",
    "RaceSession",
    "RaceResponse",
    "RaceRequest",
    "InvariantRule",
    "InvariantViolation",
    "InvariantOperator",
    "DimensionResult",
    "AnalysisDimension",
    "RaceProofError",
    "IngestionError",
    "VerificationError",
    "FormalProofError",
    "AgentSandboxError",
    "AttestationError",
]
