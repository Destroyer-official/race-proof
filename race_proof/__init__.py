"""RaceProof package initialisation."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("race-proof")
except PackageNotFoundError:
    __version__ = "0.2.0"

from race_proof.config import ProofConfig, OracleConfig, config
from race_proof.exceptions import (
    RaceProofError,
    IngestionError,
    VerificationError,
    FormalProofError,
    AgentSandboxError,
    AttestationError,
)
from race_proof.logging import get_logger, setup_logging
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
from race_proof.registry import AdapterRegistry, EngineRegistry, ExporterRegistry
from race_proof.verdict import VerdictEngine

# Compatibility alias
VerdictClass = VerdictLevel

__all__ = [
    "__version__",
    "config",
    "ProofConfig",
    "OracleConfig",
    "setup_logging",
    "get_logger",
    "AdapterRegistry",
    "EngineRegistry",
    "ExporterRegistry",
    "RaceProofError",
    "IngestionError",
    "VerificationError",
    "FormalProofError",
    "AgentSandboxError",
    "AttestationError",
    "RaceSession",
    "RaceResponse",
    "RaceRequest",
    "Verdict",
    "VerdictLevel",
    "VerdictClass",
    "VerdictEngine",
    "InvariantRule",
    "InvariantViolation",
    "InvariantOperator",
    "DimensionResult",
    "AnalysisDimension",
]


