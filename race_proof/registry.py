"""Extensible Registry Pattern for Adapters, Engines, and Exporters.

Enables future updates and third-party extensions to register new capabilities
dynamically without modifying existing core code.
"""
from __future__ import annotations

from typing import Any, Callable, Type


class AdapterRegistry:
    """Registry for attack tool log ingestion adapters."""

    _adapters: dict[str, Type[Any]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Type[Any]], Type[Any]]:
        def decorator(adapter_cls: Type[Any]) -> Type[Any]:
            cls._adapters[name.lower()] = adapter_cls
            return adapter_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Type[Any] | None:
        return cls._adapters.get(name.lower())

    @classmethod
    def list_all(cls) -> list[str]:
        return sorted(cls._adapters.keys())


class EngineRegistry:
    """Registry for concurrency verification and analysis dimensions."""

    _engines: dict[str, Type[Any]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Type[Any]], Type[Any]]:
        def decorator(engine_cls: Type[Any]) -> Type[Any]:
            cls._engines[name.lower()] = engine_cls
            return engine_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Type[Any] | None:
        return cls._engines.get(name.lower())

    @classmethod
    def list_all(cls) -> list[str]:
        return sorted(cls._engines.keys())


class ExporterRegistry:
    """Registry for evidence and report exporters."""

    _exporters: dict[str, Type[Any]] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Type[Any]], Type[Any]]:
        def decorator(exporter_cls: Type[Any]) -> Type[Any]:
            cls._exporters[name.lower()] = exporter_cls
            return exporter_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Type[Any] | None:
        return cls._exporters.get(name.lower())

    @classmethod
    def list_all(cls) -> list[str]:
        return sorted(cls._exporters.keys())

