from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer

from .models import Action
from .sources.memory_md import MemoryMdSource
from .store import GraphStore

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
    source = MemoryMdSource(str(memory))
    annotated = source.extract_annotated()
    rules = [a.rule for a in annotated]
    store = GraphStore(db_path=db)
    for rule in rules:
        store.add_rule(rule)
    return store, rules


@app.command()
def init(
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem/db", "--db", help="Database path"),
    auto: bool = typer.Option(False, "--auto", help="Skip interactive review"),
    extract_model: str = typer.Option(
        "",
        "--extract-model",
        help="LLM model for rule classification (e.g. gpt-4o-mini). "
             "Requires OPENAI_API_KEY env var. "
             "Set GRAPHMEM_LLM_BASE_URL for other OpenAI-compatible providers.",
    ),
) -> None:
    """Extract hard rules from MEMORY.md into the local graph store.

    Without --extract-model: fast keyword-only extraction (may include
    section headers and AI-behavior rules as false positives).

    With --extract-model: LLM classifies each candidate and rejects
    non-code rules. Requires pip install 'graphmem[llm]'.
    """
    if not memory.exists():
        typer.echo(f"Error: {memory} not found.", err=True)
        raise typer.Exit(1)

    source = MemoryMdSource(str(memory))
    annotated = source.extract_annotated()

    if not annotated:
        typer.echo("No candidate rules found in MEMORY.md.")
        raise typer.Exit(0)

    rules = [a.rule for a in annotated]

    # Show what was extracted with scope info
    typer.echo(f"\nFound {len(rules)} candidate rule(s):\n")
    for a in annotated:
        scope_label = ""
        if a.rule.target_files:
            tag = " (inferred)" if a.inferred_scope else ""
            scope_label = f"  → scope: {', '.join(a.rule.target_files)}{tag}"
        typer.echo(f"  [{a.rule.id}] {a.rule.content}")
        if scope_label:
            typer.echo(scope_label)

    # Optional LLM classification
    if extract_model:
        typer.echo(f"\nClassifying with {extract_model}...")
        try:
            kept, rejected = source.classify_with_llm(rules, extract_model)
        except ImportError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1)

        if rejected:
            typer.echo(f"\nRejected {len(rejected)} non-code rule(s):")
            for rule, reason in rejected:
                typer.echo(f"  ✗ [{rule.id}] {rule.content}  ({reason})")

        rules = kept
        typer.echo(f"\nKept {len(rules)} code rule(s) after LLM classification.")
    else:
        typer.echo(
            "\n[tip] Run with --extract-model gpt-4o-mini to filter out "
            "section headers and AI-behavior rules automatically."
        )

    if not rules:
        typer.echo("No code rules to save.")
        raise typer.Exit(0)

    if not auto:
        rules = source.interactive_review(rules)

    store = GraphStore(db_path=db)
    for rule in rules:
        store.add_rule(rule)

    typer.echo(f"\n✅  Saved {len(rules)} rule(s) to {db}.")


@app.command()
def scan(
    repo: Path = typer.Option(Path("."), "--repo", help="Repository to scan"),
    memory: Path = typer.Option(Path("MEMORY.md"), "--memory", help="Path to MEMORY.md"),
    db: str = typer.Option(".graphmem/db", "--db", help="Database path"),
    commit: str = typer.Option("HEAD", "--commit", help="Commit to scan (default: HEAD)"),
    threshold: float = typer.Option(
        0.85,
        "--threshold",
        help="Minimum confidence to report a violation (0.0–1.0). "
             "Higher = fewer false positives. Default: 0.85",
    ),
    extract_model: str = typer.Option(
        "",
        "--extract-model",
        help="LLM model for rule classification (same as init --extract-model)",
    ),
) -> None:
    """Scan a commit diff for rule contradictions."""
    try:
        import git
    except ImportError:
        typer.echo("gitpython is required: pip install gitpython", err=True)
        raise typer.Exit(1)

    if not memory.exists():
        typer.echo(f"Error: {memory} not found.", err=True)
        raise typer.Exit(1)

    # Load + classify rules
    source = MemoryMdSource(str(memory))
    annotated = source.extract_annotated()
    rules = [a.rule for a in annotated]

    if extract_model and rules:
        try:
            rules, rejected = source.classify_with_llm(rules, extract_model)
            if rejected:
                typer.echo(f"[LLM] Filtered out {len(rejected)} non-code rule(s).")
        except ImportError as exc:
            typer.echo(f"Warning: {exc} — using keyword extraction.", err=True)

    if not rules:
        typer.echo("No hard rules found in MEMORY.md.")
        raise typer.Exit(0)

    # Get git diff
    try:
        git_repo = git.Repo(str(repo), search_parent_directories=True)
        head = git_repo.commit(commit)
        if head.parents:
            # parent.diff(head) = changes FROM parent TO head = actual additions
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

    # Run engine
    store = GraphStore(db_path=db)
    for rule in rules:
        store.add_rule(rule)

    engine = _make_engine(store)
    all_violations = engine.check(actions)

    # Apply confidence threshold
    violations = [v for v in all_violations if v.confidence >= threshold]
    skipped = len(all_violations) - len(violations)

    typer.echo(f"Scanned {len(actions)} file(s) against {len(rules)} rule(s).")
    if skipped:
        typer.echo(
            f"[{skipped} low-confidence match(es) suppressed by --threshold {threshold}]"
        )

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
    threshold: float = typer.Option(0.85, "--threshold", help="Minimum confidence (0–1)"),
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
    all_violations = engine.check([action])
    violations = [v for v in all_violations if v.confidence >= threshold]

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
