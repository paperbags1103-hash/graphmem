from __future__ import annotations

from .models import Action, Rule, Strength, Violation

__all__ = ["Action", "GraphStore", "Rule", "Strength", "Violation"]


def __getattr__(name: str):
    if name == "GraphStore":
        from .store import GraphStore

        return GraphStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
