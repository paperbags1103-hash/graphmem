"""Integration tests: full pipeline from MEMORY.md file → engine → violations.

These tests verify the complete stack end-to-end, including scope inference,
rule storage in Kuzu, and contradiction detection — unlike unit tests which
use stub stores and synthetic rules.
"""
from __future__ import annotations

import pytest

from graphmem.engine import ContradictionEngine
from graphmem.models import Action
from graphmem.sources.memory_md import MemoryMdSource
from graphmem.store import GraphStore


def _make_engine(tmp_path, memory_content: str) -> ContradictionEngine:
    memory_file = tmp_path / "MEMORY.md"
    memory_file.write_text(memory_content, encoding="utf-8")

    source = MemoryMdSource(str(memory_file))
    rules = source.extract()

    db_path = str(tmp_path / "db")
    store = GraphStore(db_path=db_path)
    for rule in rules:
        store.add_rule(rule)

    return ContradictionEngine(store)


# ---------------------------------------------------------------------------
# Scope inference + VersionPinMatcher alignment
# ---------------------------------------------------------------------------


def test_version_pin_fires_on_package_json(tmp_path):
    """react-grid-layout version pin must detect changes in package.json.

    This is the Gap #4 regression test (Opus pre-release review):
    previously, 'react' in the rule name caused scope to be *.ts/*.jsx,
    so package.json was excluded and the violation was missed.
    """
    engine = _make_engine(
        tmp_path,
        "## Tech Stack\n- `react-grid-layout` v1.4.4 고정\n",
    )

    action = Action(
        type="git_commit",
        target="package.json",
        diff='+ "react-grid-layout": "2.0.0"',
    )
    violations = engine.check([action])

    assert len(violations) == 1
    assert "1.4.4" in violations[0].reason or "2.0.0" in violations[0].reason


def test_version_pin_does_not_fire_on_unrelated_ts_file(tmp_path):
    """Version pin rule must not fire on a TS file that doesn't change the version."""
    engine = _make_engine(
        tmp_path,
        "## Tech Stack\n- `react-grid-layout` v1.4.4 고정\n",
    )

    action = Action(
        type="git_commit",
        target="src/components/Grid.tsx",
        diff="+ export default function Grid() { return <div />; }",
    )
    violations = engine.check([action])

    assert violations == []


def test_scope_inference_shown_in_extracted_rules(tmp_path):
    """Scope inference must annotate version pin rules with package manifest files."""
    memory_file = tmp_path / "MEMORY.md"
    memory_file.write_text("- `react-grid-layout` v1.4.4 고정\n", encoding="utf-8")

    source = MemoryMdSource(str(memory_file))
    rules = source.extract()

    assert len(rules) == 1
    assert "package.json" in rules[0].target_files


# ---------------------------------------------------------------------------
# Shell-command scope — no false positives on Python files
# ---------------------------------------------------------------------------


def test_forbidden_cmd_scope_excludes_python_files(tmp_path):
    """Shell-command forbidden rules must not fire on Python source files."""
    engine = _make_engine(
        tmp_path,
        "- `rm -rf` 절대 금지\n",
    )

    # Python file using open() — should NOT trigger rm -rf rule
    action = Action(
        type="git_commit",
        target="exchange.py",
        diff="+ def open_limit_long(self): pass",
    )
    violations = engine.check([action])

    assert violations == []


def test_forbidden_cmd_fires_on_shell_file(tmp_path):
    """Shell-command forbidden rules must fire when added to a shell script."""
    engine = _make_engine(
        tmp_path,
        "- `rm -rf` 절대 금지\n",
    )

    action = Action(
        type="git_commit",
        target="deploy.sh",
        diff="+ rm -rf /tmp/build",
    )
    violations = engine.check([action])

    assert len(violations) == 1


# ---------------------------------------------------------------------------
# Header filtering
# ---------------------------------------------------------------------------


def test_section_headers_are_not_extracted_as_rules(tmp_path):
    """Markdown section headers containing keywords must be filtered out."""
    memory_file = tmp_path / "MEMORY.md"
    memory_file.write_text(
        "### 기술 스택 (절대 바꾸지 말 것)\n"
        "- `react-grid-layout` v1.4.4 고정\n",
        encoding="utf-8",
    )

    source = MemoryMdSource(str(memory_file))
    rules = source.extract()

    # Only the version pin rule, not the section header
    assert len(rules) == 1
    assert "기술 스택" not in rules[0].content


# ---------------------------------------------------------------------------
# Vite value pin
# ---------------------------------------------------------------------------


def test_vite_value_pin_scoped_to_vite_config(tmp_path):
    """Vite base value pin must apply to vite.config.* files."""
    engine = _make_engine(
        tmp_path,
        "- Vite `base: './'` 고정\n",
    )

    # Wrong base value in vite.config.ts → should detect
    action = Action(
        type="git_commit",
        target="vite.config.ts",
        diff="+ export default defineConfig({ base: '/app/' })",
    )
    violations = engine.check([action])

    assert len(violations) == 1


def test_vite_rule_does_not_fire_on_python_file(tmp_path):
    """Vite rule must not fire on Python or unrelated files."""
    engine = _make_engine(
        tmp_path,
        "- Vite `base: './'` 고정\n",
    )

    action = Action(
        type="git_commit",
        target="server/api.py",
        diff="+ BASE_URL = '/app/'",
    )
    violations = engine.check([action])

    assert violations == []
