"""Centralized Configuration and Runtime Settings for RaceProof.

Loads settings from environment variables (prefixed with RACE_PROOF_)
with sensible offline-first defaults.
"""
from __future__ import annotations

import os
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field


def _find_default_model() -> Path | None:
    env_m = os.getenv("RACE_PROOF_MODEL_PATH")
    if env_m and Path(env_m).exists():
        return Path(env_m)

    root = Path(__file__).resolve().parent.parent / "model"
    if root.exists():
        target = root / "Huihui-Qwen3.5-4B-abliterated.Q4_K_M.gguf"
        if target.exists():
            return target
        ggufs = list(root.glob("*.gguf"))
        if ggufs:
            return ggufs[0]
    return None


class OracleConfig(BaseModel):
    """Runtime configuration settings for RaceProof verification pipelines."""

    log_level: str = Field(
        default_factory=lambda: os.getenv("RACE_PROOF_LOG_LEVEL", "INFO").upper()
    )
    model_path: Path | None = Field(
        default_factory=_find_default_model
    )
    sandbox_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("RACE_PROOF_SANDBOX_TIMEOUT", "5.0"))
    )
    sandbox_memory_mb: int = Field(
        default_factory=lambda: int(os.getenv("RACE_PROOF_SANDBOX_MEMORY_MB", "256"))
    )
    max_workers: int = Field(
        default_factory=lambda: int(os.getenv("RACE_PROOF_WORKERS", "4"))
    )
    default_output_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("RACE_PROOF_OUTPUT_DIR", "race_proof_findings"))
    )
    rust_enabled: bool = Field(
        default_factory=lambda: os.getenv("RACE_PROOF_DISABLE_RUST", "0").lower() not in ("1", "true")
    )
    enable_agent: bool = Field(
        default_factory=lambda: os.getenv("RACE_PROOF_ENABLE_AGENT", "1").lower() in ("1", "true")
    )
    sarif_version: str = "2.1.0"
    corpus_dir: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "race_proof_bench"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


# Global default configuration singleton
config = OracleConfig()
