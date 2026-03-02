from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from graphmem.models import Action, Rule


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _models_module() -> Any:
    return pytest.importorskip("graphmem.models", reason="graphmem models are not available yet")


@pytest.fixture()
def sample_memory_path() -> Path:
    return FIXTURES_DIR / "sample_memory.md"


@pytest.fixture()
def sample_memory_text(sample_memory_path: Path) -> str:
    return sample_memory_path.read_text(encoding="utf-8")


@pytest.fixture()
def build_rule() -> Any:
    models = _models_module()

    def _build_rule(**overrides: Any) -> Rule:
        defaults = {
            "id": "rule-1",
            "content": "Vite base='./' 고정",
            "strength": models.Strength.HARD,
            "scope": "",
            "source_file": "MEMORY.md",
            "source_line": 1,
            "pattern": "",
            "target_files": [],
        }
        defaults.update(overrides)
        return models.Rule(**defaults)

    return _build_rule


@pytest.fixture()
def build_action() -> Any:
    models = _models_module()

    def _build_action(**overrides: Any) -> Action:
        defaults = {
            "type": "modify",
            "target": "vite.config.ts",
            "agent": "pytest",
            "diff": "",
        }
        defaults.update(overrides)
        return models.Action(**defaults)

    return _build_action


@pytest.fixture()
def hard_rules(build_rule: Any) -> list[Rule]:
    return [
        build_rule(
            id="vite-base",
            content="Vite base='./' 고정",
            scope="vite.config.ts",
            target_files=["vite.config.ts"],
        ),
        build_rule(
            id="lightweight-charts",
            content="lightweight-charts v4.2.0 고정",
            scope="package.json",
            target_files=["package.json"],
        ),
        build_rule(
            id="rm-rf",
            content="절대 rm -rf 사용 금지",
            scope="*.sh",
            target_files=["*.sh"],
        ),
        build_rule(
            id="api-key",
            content="API 키 하드코딩 금지 — .env 사용",
            scope="src/**/*.ts",
            target_files=["src/**/*.ts", "src/*.ts"],
        ),
        build_rule(
            id="react-leaflet",
            content="react-leaflet v4.2.1 고정",
            scope="package.json",
            target_files=["package.json"],
        ),
    ]
