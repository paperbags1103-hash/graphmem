from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer

from .models import Action
from .sources.memory_md import MemoryMdSource
from .store import GraphStore

# FIX (Opus review #5): previous CLI tried to import a non-existent GraphMem class
# and relied on _invoke_method duck-typing to route arguments. Rewritten to call
# the actual components (MemoryMdSource, ContradictionEngine, GraphStore) directly.

app = typer.Typer(
    help="graphmem — contradiction detection for AI agent rules.",
    add_completion=False,
)


def _make_engine(store: GraphStore) -> Any:
    from .engine import ContradictionEngine

    return ContradictionEngine(store)


def _format_violation(v: Any, index: int) -> str:
    lines = [
        f"⚠️  위반 #{index} (신뢰도 {v.confidence:.0%})",
        f"   규칙: {v.rule.content}",
        f"   출처: {v.rule.source_file}:{v.rule.source_line}",
        f"   이유: {v.reason}",
        f"   파일: {v.action.target}",
    ]
    return "\n".join(lines)


def _load_and_store_rules(memory: Path, db: str) -> tuple[GraphStore, list[Any]]:
    """Extract rules from MEMORY.md and upsert them into the store."""
    source = MemoryMdSource(str(memory))
    rules = source.extract()
    store = GraphStore(db_path=db)
    for rule in rules:
        store.add_rule(rule)
    return store, rules


@app.command()
def init(
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem/db", "--db", help="Database path"),
    auto: bool = typer.Option(False, "--auto", help="Skip interactive review"),
) -> None:
    """Extract hard rules from MEMORY.md into the local graph store."""
    if not memory.exists():
        typer.echo(f"Error: {memory} not found.", err=True)
        raise typer.Exit(1)

    source = MemoryMdSource(str(memory))
    rules = source.extract()

    if not rules:
        typer.echo("No hard rules found in MEMORY.md.")
        raise typer.Exit(0)

    typer.echo(f"Found {len(rules)} hard rule(s).")

    if not auto:
        rules = source.interactive_review(rules)

    store = GraphStore(db_path=db)
    for rule in rules:
        store.add_rule(rule)

    typer.echo(f"✅  Saved {len(rules)} rule(s) to {db}.")


@app.command()
def scan(
    repo: Path = typer.Option(Path("."), "--repo", help="Repository to scan"),
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem/db", "--db", help="Database path"),
    commit: str = typer.Option("HEAD", "--commit", help="Commit to scan (default: HEAD)"),
) -> None:
    """Scan the most recent commit diff for rule contradictions."""
    try:
        import git
    except ImportError:
        typer.echo("gitpython is required: pip install gitpython", err=True)
        raise typer.Exit(1)

    if not memory.exists():
        typer.echo(f"Error: {memory} not found.", err=True)
        raise typer.Exit(1)

    # Get git diff
    try:
        git_repo = git.Repo(str(repo), search_parent_directories=True)
        head = git_repo.commit(commit)
        if head.parents:
            # FIX: parent.diff(head) = changes FROM parent TO head = actual commit additions.
            # head.diff(parent) is reversed — "+" lines are what got REMOVED, not added.
            diffs = head.parents[0].diff(head, create_patch=True)
        else:
            diffs = head.diff(git.NULL_TREE, create_patch=True)
    except Exception as exc:
        typer.echo(f"Git error: {exc}", err=True)
        raise typer.Exit(1)

    # Build actions from diff
    actions: list[Action] = []
    for diff_item in diffs:
        file_path = diff_item.b_path or diff_item.a_path or ""
        diff_text = ""
        try:
            diff_text = (
                diff_item.diff.decode("utf-8", errors="replace") if diff_item.diff else ""
            )
        except Exception:
            pass
        actions.append(Action(type="git_commit", target=file_path, diff=diff_text))

    if not actions:
        typer.echo("No file changes found in commit.")
        raise typer.Exit(0)

    store, rules = _load_and_store_rules(memory, db)
    typer.echo(f"Loaded {len(rules)} rule(s) from {memory}.")

    engine = _make_engine(store)
    violations = engine.check(actions)

    if not violations:
        typer.echo("✅  No violations detected.")
    else:
        typer.echo(f"\n🚨  {len(violations)} violation(s) detected:\n")
        for i, v in enumerate(violations, 1):
            typer.echo(_format_violation(v, i))
            typer.echo()
        raise typer.Exit(1)


@app.command()
def check(
    file: Path = typer.Argument(..., help="File path to check"),
    diff_input: str = typer.Option("", "--diff", help="Diff content (or pipe via stdin)"),
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem/db", "--db", help="Database path"),
) -> None:
    """Check a single file's diff against stored rules (pipe diff via stdin)."""
    if not memory.exists():
        typer.echo(f"Error: {memory} not found.", err=True)
        raise typer.Exit(1)

    diff_text = diff_input
    if not diff_text and not sys.stdin.isatty():
        diff_text = sys.stdin.read()

    store, rules = _load_and_store_rules(memory, db)
    engine = _make_engine(store)
    action = Action(type="file_check", target=str(file), diff=diff_text)
    violations = engine.check([action])

    if not violations:
        typer.echo("✅  No violations detected.")
    else:
        typer.echo(f"\n🚨  {len(violations)} violation(s) detected:\n")
        for i, v in enumerate(violations, 1):
            typer.echo(_format_violation(v, i))
            typer.echo()
        raise typer.Exit(1)


@app.command()
def status(
    db: str = typer.Option(".graphmem/db", "--db", help="Database path"),
) -> None:
    """Show rule and violation counts in the graph store."""
    store = GraphStore(db_path=db)
    rule_count = len(store.get_rules(strength="hard"))
    violation_count = len(store.get_violations())
    typer.echo(f"Rules:      {rule_count}")
    typer.echo(f"Violations: {violation_count}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
