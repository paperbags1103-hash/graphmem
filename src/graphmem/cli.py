from __future__ import annotations

from collections.abc import Callable, Iterable
from inspect import Parameter, signature
from pathlib import Path
from typing import Any

import typer

from .store import GraphStore

app = typer.Typer(help="Graph-backed memory checks for repository rules.")


def _load_graphmem() -> type[Any]:
    try:
        from graphmem import GraphMem  # type: ignore[attr-defined]
    except (ImportError, AttributeError) as exc:
        typer.echo(
            "GraphMem is not available yet. Install the remaining core modules before using this command.",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    return GraphMem


def _invoke_method(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        params = signature(method).parameters
    except (TypeError, ValueError):
        return method(*args, **kwargs)

    filtered_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in params and params[key].kind in (Parameter.KEYWORD_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
    }
    return method(*args, **filtered_kwargs)


def _render_violations(violations: Iterable[Any]) -> None:
    count = 0
    for count, violation in enumerate(violations, start=1):
        typer.echo(str(violation))

    if count == 0:
        typer.echo("No violations found.")


def _graphmem_instance(db: str) -> Any:
    graphmem_cls = _load_graphmem()

    for kwargs in ({"db_path": db}, {"db": db}, {}):
        try:
            return graphmem_cls(**kwargs)
        except TypeError:
            continue

    return graphmem_cls()


@app.command()
def init(
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem", "--db", help="Database directory"),
    auto: bool = typer.Option(False, "--auto", help="Accept extracted onboarding rules automatically"),
) -> None:
    """Extract onboarding rules from MEMORY.md into the local graph store."""

    gm = _graphmem_instance(db)
    _invoke_method(gm.init, memory_path=str(memory), db_path=db, auto=auto)
    typer.echo(f"Initialized graphmem from {memory}.")


@app.command()
def check(
    file: Path = typer.Argument(..., help="Single file to inspect"),
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem", "--db", help="Database directory"),
) -> None:
    """Check one file against stored hard rules."""

    gm = _graphmem_instance(db)
    violations = _invoke_method(
        gm.check,
        str(file),
        memory_path=str(memory),
        db_path=db,
    )
    _render_violations(violations or [])


@app.command()
def scan(
    repo: Path = typer.Option(Path("."), "--repo", help="Repository to scan"),
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem", "--db", help="Database directory"),
) -> None:
    """Scan the most recent commit for contradictions."""

    gm = _graphmem_instance(db)
    violations = _invoke_method(
        gm.scan,
        repo_path=str(repo),
        repo=str(repo),
        memory_path=str(memory),
        db_path=db,
    )
    _render_violations(violations or [])


@app.command()
def status(
    db: str = typer.Option(".graphmem", "--db", help="Database directory"),
) -> None:
    """Show the current rule and violation counts."""

    store = GraphStore(db_path=db)
    rule_count = len(store.get_rules(strength="hard"))
    violation_count = len(store.get_violations())
    typer.echo(f"Rules: {rule_count}")
    typer.echo(f"Violations: {violation_count}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
