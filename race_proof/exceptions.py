"""Typed Exception Hierarchy for RaceProof.

All domain-specific errors inherit from `RaceProofError` to enable precise error
handling, structured error telemetry, and clean failure modes across CI/CD and TuI.
"""
from __future__ import annotations


class RaceProofError(Exception):
    """Base exception for all RaceProof runtime and analysis errors."""

    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        if self.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} [{ctx_str}]"
        return self.message


# ---------------------------------------------------------------------------
# Ingestion Exceptions
# ---------------------------------------------------------------------------

class IngestionError(RaceProofError):
    """Raised when parsing or normalizing an attack tool log fails."""
    pass


class UnsupportedFormatError(IngestionError):
    """Raised when auto-detect cannot determine the attack tool export format."""
    pass


class CorruptPayloadError(IngestionError):
    """Raised when an input log file is malformed, truncated, or unparseable."""
    pass


# ---------------------------------------------------------------------------
# Analysis & Verification Exceptions
# ---------------------------------------------------------------------------

class VerificationError(RaceProofError):
    """Raised when verification pipeline encounters an unexpected analysis failure."""
    pass


class InvariantEvaluationError(VerificationError):
    """Raised when evaluating a business invariant rule expression fails."""
    pass


class StatisticalAnalysisError(VerificationError):
    """Raised when hypothesis testing or confidence interval estimation fails."""
    pass


# ---------------------------------------------------------------------------
# Formal Verification Exceptions
# ---------------------------------------------------------------------------

class FormalProofError(RaceProofError):
    """Raised when mathematical state-space model checking fails."""
    pass


class StateSpaceExhaustionError(FormalProofError):
    """Raised when state space exploration exceeds the configured safety ceiling."""
    pass


# ---------------------------------------------------------------------------
# Agent & Sandbox Exceptions
# ---------------------------------------------------------------------------

class AgentSandboxError(RaceProofError):
    """Base exception for agent execution, sandbox, and synthesis errors."""
    pass


class ToolExecutionTimeoutError(AgentSandboxError):
    """Raised when a sandboxed tool exceeds its CPU wall-clock limit."""
    pass


class ToolMemoryCeilingError(AgentSandboxError):
    """Raised when a sandboxed tool exceeds its memory ceiling."""
    pass


class SecurityViolationError(AgentSandboxError):
    """Raised when untrusted input triggers PromptGuard or attempts sandbox escape."""
    pass


# ---------------------------------------------------------------------------
# Evidence & Cryptographic Exceptions
# ---------------------------------------------------------------------------

class EvidencePackagingError(RaceProofError):
    """Raised when assembling or rendering evidence bundles fails."""
    pass


class AttestationError(RaceProofError):
    """Raised when cryptographic signing or verification of an attestation fails."""
    pass

