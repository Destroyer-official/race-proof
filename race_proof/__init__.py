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
from race_proof.registry import AdapterRegistry, EngineRegistry, ExporterRegistry

__all__ = [
    "__version__",
    "config",
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
]

