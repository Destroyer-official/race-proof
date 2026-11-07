"""Base adapter interface for ingestion."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from race_proof.models import RaceSession


class BaseAdapter(ABC):
    """
    Abstract base class for all ingestion adapters.
    
    Each adapter converts the output of a specific race attack tool
    (Turbo Intruder, QuicDraw, Nuclei, etc.) into a list of RaceSession
    objects that the oracle engine can process.
    """

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Human-readable name of the source tool."""
        ...

    @abstractmethod
    def parse(self, source: str | Path) -> list[RaceSession]:
        """
        Parse the tool's output file and return RaceSessions.

        Parameters
        ----------
        source:
            Path to the tool's output file, or a raw string of that content.

        Returns
        -------
        list[RaceSession]
            One or more race sessions extracted from the input.
        """
        ...

    def parse_string(self, content: str) -> list[RaceSession]:
        """Parse from a raw string. Adapters may override for efficiency."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                        delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp = f.name
        try:
            return self.parse(tmp)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

