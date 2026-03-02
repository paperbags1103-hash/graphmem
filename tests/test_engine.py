from __future__ import annotations

from typing import Any

import pytest


class _StubStore:
    def __init__(self, rules: list[Any]) -> None:
        self._rules = rules
        self.logged: list[tuple[Any, Any, Any]] = []

    def get_rules(self, strength: str = "hard") -> list[Any]:
        if strength == "hard":
            return self._rules
        return []

    def add_violation(self, action: Any, rule: Any, violation: Any) -> None:
        self.logged.append((action, rule, violation))


@pytest.fixture()
def engine(hard_rules: list[Any]) -> Any:
    engine_module = pytest.importorskip("graphmem.engine", reason="engine module is not available yet")
    return engine_module.ContradictionEngine(_StubStore(hard_rules))


def test_detects_vite_base_violation(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="vite.config.ts",
        diff="+ export default defineConfig({ base: '/app/' })",
    )

    violations = engine.check([action])

    assert len(violations) == 1
    assert "Vite base='./' 고정" in violations[0].rule.content


def test_detects_lightweight_charts_version_violation(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="package.json",
        diff='+ "lightweight-charts": "v5.0.0"',
    )

    violations = engine.check([action])

    assert len(violations) == 1
    assert "lightweight-charts v4.2.0 고정" in violations[0].rule.content


def test_detects_rm_rf_violation(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="deploy.sh",
        diff="+ rm -rf /tmp/build",
    )

    violations = engine.check([action])

    assert len(violations) == 1
    assert "rm -rf" in violations[0].rule.content


def test_detects_hardcoded_api_key_violation(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="src/api.ts",
        diff='+ export const OPENAI_API_KEY = "sk-proj-xxxxx";',
    )

    violations = engine.check([action])

    assert len(violations) == 1
    assert "API 키 하드코딩 금지" in violations[0].rule.content


def test_detects_react_leaflet_version_violation(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="package.json",
        diff='+ "react-leaflet": "react-leaflet@5"',
    )

    violations = engine.check([action])

    assert len(violations) == 1
    assert "react-leaflet v4.2.1 고정" in violations[0].rule.content


def test_ignores_vite_rule_for_unrelated_file(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="src/styles/main.css",
        diff="+ body { color: red; }",
    )

    violations = engine.check([action])

    assert violations == []


def test_ignores_rm_rf_rule_for_package_json(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="package.json",
        diff='+ "scripts": { "clean": "rimraf dist" }',
    )

    violations = engine.check([action])

    assert violations == []


def test_ignores_readme_changes(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="README.md",
        diff="+ Added getting started docs",
    )

    violations = engine.check([action])

    assert violations == []


def test_ignores_version_pin_rule_for_component_change(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="src/components/Button.tsx",
        diff="+ export function Button() { return <button />; }",
    )

    violations = engine.check([action])

    assert violations == []


def test_ignores_vite_file_when_base_does_not_change(engine: Any, build_action: Any) -> None:
    action = build_action(
        target="vite.config.ts",
        diff="+ export default defineConfig({ server: { port: 5173 } })",
    )

    violations = engine.check([action])

    assert violations == []
