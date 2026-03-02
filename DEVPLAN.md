# graphmem 개발 플랜

## 1. Phase별 개발 계획

### Phase 0: 프로젝트 셋업 (Day 1-2)
- [ ] GitHub repo 생성, pyproject.toml, CI
- [ ] Kuzu 임베디드 DB 연동 확인 (hello world)
- [ ] 스키마 DDL 작성 및 마이그레이션

### Phase 1: 코어 엔진 (Week 1)
- [ ] `Rule`, `File`, `Action` 데이터 모델
- [ ] `RuleSource` 인터페이스 + `MemoryMdSource` 구현
- [ ] `ActionDetector` 인터페이스 + `FileChangeDetector` 구현
- [ ] `ContradictionEngine.check()` — 핵심 모순 감지 로직
- [ ] 10개 테스트셋 전부 통과

### Phase 2: 온보딩 & CLI (Week 2)
- [ ] MEMORY.md 파서 (키워드 추출: 절대/금지/고정/never/must not)
- [ ] `graphmem init` — 규칙 후보 추출 → 대화형 검수
- [ ] `graphmem check <file>` — 단일 파일 체크
- [ ] `graphmem check --diff` — git diff 기반 체크

### Phase 3: OpenClaw 통합 (Week 3)
- [ ] Python API (`GraphMem` 클래스) 안정화
- [ ] OpenClaw 스킬로 래핑 (MCP 또는 직접 호출)
- [ ] 에이전트가 파일 수정 전 자동 체크하는 훅

### Phase 4: 배포 (Week 3-4)
- [ ] PyPI 배포
- [ ] README, 예제, GIF 데모
- [ ] GitHub Actions CI/CD

---

## 2. 디렉토리 구조

```
graphmem/
├── pyproject.toml
├── README.md
├── LICENSE                    # MIT
├── src/
│   └── graphmem/
│       ├── __init__.py        # public API re-export
│       ├── models.py          # Rule, File, Action dataclasses
│       ├── schema.py          # Kuzu DDL, DB init
│       ├── store.py           # GraphStore (Kuzu CRUD)
│       ├── engine.py          # ContradictionEngine
│       ├── interfaces.py      # RuleSource, ActionDetector ABCs
│       ├── sources/
│       │   ├── __init__.py
│       │   └── memory_md.py   # MemoryMdSource
│       ├── detectors/
│       │   ├── __init__.py
│       │   └── file_change.py # FileChangeDetector (git diff)
│       └── cli.py             # typer CLI
├── tests/
│   ├── conftest.py
│   ├── test_engine.py         # 10개 테스트셋
│   ├── test_sources.py
│   ├── test_store.py
│   └── fixtures/
│       ├── sample_memory.md
│       └── sample_diffs/
└── examples/
    └── quickstart.py
```

---

## 3. 핵심 인터페이스 설계

```python
# src/graphmem/models.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class Strength(str, Enum):
    HARD = "hard"
    SOFT = "soft"

@dataclass
class Rule:
    id: str
    content: str                          # "Vite base='./' 고정"
    strength: Strength = Strength.HARD
    scope: str = ""                       # glob pattern: "vite.config.*"
    source_file: str = ""
    source_line: int = 0
    # 파싱된 구조화 정보
    pattern: str = ""                     # 매칭할 정규식 or 키워드
    target_files: list[str] = field(default_factory=list)  # glob patterns

@dataclass
class Action:
    type: str          # "modify", "delete", "add"
    target: str        # file path
    agent: str = ""    # "human", "claude", "copilot"
    timestamp: datetime = field(default_factory=datetime.now)
    diff: str = ""     # unified diff content

@dataclass
class Violation:
    rule: Rule
    action: Action
    confidence: float  # 0.0 ~ 1.0
    reason: str        # 사람이 읽을 수 있는 설명
```

```python
# src/graphmem/interfaces.py
from abc import ABC, abstractmethod
from .models import Rule, Action

class RuleSource(ABC):
    """규칙을 추출하는 소스. MEMORY.md, .graphmem.yml, etc."""
    @abstractmethod
    def extract(self) -> list[Rule]:
        ...

class ActionDetector(ABC):
    """변경 사항을 감지하는 디텍터. git diff, file watcher, etc."""
    @abstractmethod
    def detect(self) -> list[Action]:
        ...
```

```python
# src/graphmem/engine.py
from .models import Rule, Action, Violation
from .store import GraphStore
import re, fnmatch

class ContradictionEngine:
    def __init__(self, store: GraphStore):
        self.store = store
        self._matchers: list[RuleMatcher] = [
            VersionPinMatcher(),    # "v4.2.0 고정" 패턴
            ForbiddenCmdMatcher(),  # "금지" 패턴
            ValuePinMatcher(),      # "base='./' 고정" 패턴
            SecretLeakMatcher(),    # "하드코딩 금지" 패턴
        ]

    def check(self, actions: list[Action]) -> list[Violation]:
        violations = []
        rules = self.store.get_rules(strength="hard")
        for action in actions:
            relevant = self._relevant_rules(rules, action)
            for rule in relevant:
                for matcher in self._matchers:
                    v = matcher.match(rule, action)
                    if v and v.confidence >= 0.7:
                        violations.append(v)
                        self.store.add_violation(action, rule, v)
                        break
        return violations

    def _relevant_rules(self, rules: list[Rule], action: Action) -> list[Rule]:
        """scope/target_files로 관련 규칙만 필터링 — false positive 방지 핵심"""
        result = []
        for r in rules:
            if not r.target_files:  # scope 없으면 전체 적용
                result.append(r)
            elif any(fnmatch.fnmatch(action.target, pat) for pat in r.target_files):
                result.append(r)
        return result


class RuleMatcher(ABC):
    """규칙 유형별 매칭 전략"""
    @abstractmethod
    def match(self, rule: Rule, action: Action) -> Violation | None: ...


class VersionPinMatcher(RuleMatcher):
    """'XXX v1.2.3 고정' 패턴 → diff에서 버전 변경 감지"""
    VERSION_RE = re.compile(r'["\']?\^?~?(\d+\.\d+\.\d+)["\']?')

    def match(self, rule: Rule, action: Action) -> Violation | None:
        # rule.content에서 패키지명 + 버전 추출
        # action.diff에서 해당 패키지 버전 변경 감지
        # 다르면 Violation 반환
        ...


class ForbiddenCmdMatcher(RuleMatcher):
    """'XXX 사용 금지' → diff에 해당 명령어 추가 감지"""
    def match(self, rule: Rule, action: Action) -> Violation | None:
        # rule.content에서 금지 대상 추출
        # action.diff의 +줄에서 해당 패턴 검색
        ...
```

```python
# src/graphmem/store.py
import kuzu

class GraphStore:
    def __init__(self, db_path: str = ".graphmem/db"):
        self.db = kuzu.Database(db_path)
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def _init_schema(self):
        ddl = [
            "CREATE NODE TABLE IF NOT EXISTS Rule(id STRING, content STRING, strength STRING, scope STRING, source_file STRING, source_line INT64, pattern STRING, PRIMARY KEY(id))",
            "CREATE NODE TABLE IF NOT EXISTS File(path STRING, PRIMARY KEY(path))",
            "CREATE NODE TABLE IF NOT EXISTS Action(id STRING, type STRING, target STRING, agent STRING, timestamp TIMESTAMP, PRIMARY KEY(id))",
            "CREATE REL TABLE IF NOT EXISTS CONSTRAINS(FROM Rule TO File)",
            "CREATE REL TABLE IF NOT EXISTS MODIFIES(FROM Action TO File)",
            "CREATE REL TABLE IF NOT EXISTS VIOLATES(FROM Action TO Rule, confidence DOUBLE, reason STRING)",
        ]
        for stmt in ddl:
            self.conn.execute(stmt)

    def add_rule(self, rule: Rule) -> None: ...
    def get_rules(self, strength: str = None) -> list[Rule]: ...
    def add_action(self, action: Action) -> None: ...
    def add_violation(self, action: Action, rule: Rule, v: Violation) -> None: ...
    def get_violations(self, since: datetime = None) -> list[Violation]: ...
```

```python
# src/graphmem/sources/memory_md.py
import re
from ..interfaces import RuleSource
from ..models import Rule, Strength

KEYWORDS = re.compile(r'(절대|금지|고정|never|must not|do not|하지\s*말)', re.IGNORECASE)

class MemoryMdSource(RuleSource):
    def __init__(self, path: str = "MEMORY.md"):
        self.path = path

    def extract(self) -> list[Rule]:
        rules = []
        with open(self.path) as f:
            for i, line in enumerate(f, 1):
                if KEYWORDS.search(line):
                    rules.append(Rule(
                        id=f"memory-L{i}",
                        content=line.strip().lstrip("-").strip(),
                        strength=Strength.HARD,
                        source_file=self.path,
                        source_line=i,
                    ))
        return rules
```

```python
# src/graphmem/cli.py
import typer
from .sources.memory_md import MemoryMdSource
from .store import GraphStore
from .engine import ContradictionEngine
from .detectors.file_change import FileChangeDetector

app = typer.Typer()

@app.command()
def init(memory: str = "MEMORY.md"):
    """MEMORY.md에서 규칙 후보 추출 → 대화형 검수"""
    source = MemoryMdSource(memory)
    candidates = source.extract()
    store = GraphStore()
    for c in candidates:
        print(f"\n📋 규칙 후보: {c.content}")
        print(f"   출처: {c.source_file}:{c.source_line}")
        choice = input("   등록? [Y/n/e(dit)] ").strip().lower()
        if choice in ("", "y"):
            store.add_rule(c)
            print("   ✅ 등록됨")
        elif choice == "e":
            c.content = input("   수정: ")
            store.add_rule(c)
            print("   ✅ 수정 후 등록됨")
        else:
            print("   ⏭️  건너뜀")

@app.command()
def check(diff: bool = False, file: str = None):
    """모순 체크"""
    store = GraphStore()
    engine = ContradictionEngine(store)
    detector = FileChangeDetector(diff=diff, file=file)
    actions = detector.detect()
    violations = engine.check(actions)
    if not violations:
        print("✅ 모순 없음")
    for v in violations:
        print(f"🚨 위반: {v.reason}")
        print(f"   규칙: {v.rule.content}")
        print(f"   파일: {v.action.target}")
        print(f"   신뢰도: {v.confidence:.0%}")
```

```python
# src/graphmem/__init__.py
"""graphmem — Contradiction detection for AI agents"""
from .models import Rule, Action, Violation, Strength
from .store import GraphStore
from .engine import ContradictionEngine

__all__ = ["Rule", "Action", "Violation", "Strength", "GraphStore", "ContradictionEngine"]
```

---

## 4. OpenClaw 통합 방법

OpenClaw 에이전트가 파일 수정 시 자동으로 모순 체크하는 흐름:

```python
# openclaw 스킬 또는 훅에서:
from graphmem import GraphStore, ContradictionEngine
from graphmem.detectors.file_change import FileChangeDetector

def pre_commit_check() -> str:
    """에이전트가 파일 수정 후, 커밋 전 자동 호출"""
    store = GraphStore()
    engine = ContradictionEngine(store)
    detector = FileChangeDetector(diff=True)  # git diff --staged
    violations = engine.check(detector.detect())
    if violations:
        msg = "🚨 규칙 위반 감지:\n"
        for v in violations:
            msg += f"- {v.rule.content} → {v.action.target} ({v.confidence:.0%})\n"
        return msg
    return ""
```

**통합 단계:**
1. OpenClaw 워크스페이스에 `graphmem init` 실행 → MEMORY.md에서 규칙 등록
2. 에이전트 파이프라인에 `pre_commit_check()` 훅 추가
3. 위반 시 에이전트에게 경고 → 수정 또는 사용자 확인 요청

---

## 5. 테스트 전략

```python
# tests/test_engine.py
import pytest
from graphmem import Rule, Action, ContradictionEngine, GraphStore, Strength

@pytest.fixture
def engine(tmp_path):
    store = GraphStore(str(tmp_path / "db"))
    # 규칙 5개 등록
    rules = [
        Rule(id="r1", content="Vite base='./' 고정", strength=Strength.HARD,
             target_files=["vite.config.*"], pattern="base\\s*[=:]\\s*['\"]([^'\"]+)"),
        Rule(id="r2", content="lightweight-charts v4.2.0 고정", strength=Strength.HARD,
             target_files=["package.json"], pattern="lightweight-charts.*?(\\d+\\.\\d+\\.\\d+)"),
        Rule(id="r3", content="rm -rf 사용 금지", strength=Strength.HARD,
             target_files=["*"], pattern="rm\\s+-rf"),
        Rule(id="r4", content="API 키 하드코딩 금지", strength=Strength.HARD,
             target_files=["*.py", "*.ts", "*.js"], pattern="sk-[a-zA-Z0-9]{20,}"),
        Rule(id="r5", content="react-leaflet v4.2.1 고정", strength=Strength.HARD,
             target_files=["package.json"], pattern="react-leaflet.*?(\\d+\\.\\d+\\.\\d+)"),
    ]
    for r in rules:
        store.add_rule(r)
    return ContradictionEngine(store)

# === 모순 O (5개) — 전부 감지해야 함 ===

def test_vite_base_change(engine):
    action = Action(type="modify", target="vite.config.ts",
                    diff="+  base: '/',")
    violations = engine.check([action])
    assert len(violations) >= 1
    assert any("base" in v.reason.lower() or "vite" in v.reason.lower() for v in violations)

def test_version_upgrade(engine):
    action = Action(type="modify", target="package.json",
                    diff='-    "lightweight-charts": "4.2.0"\n+    "lightweight-charts": "5.0.0"')
    violations = engine.check([action])
    assert len(violations) >= 1

def test_rm_rf_added(engine):
    action = Action(type="modify", target="deploy.sh",
                    diff="+rm -rf /tmp/build")
    violations = engine.check([action])
    assert len(violations) >= 1

def test_api_key_hardcoded(engine):
    action = Action(type="modify", target="config.py",
                    diff='+API_KEY = "sk-abc123def456ghi789jkl012mno"')
    violations = engine.check([action])
    assert len(violations) >= 1

def test_react_leaflet_upgrade(engine):
    action = Action(type="modify", target="package.json",
                    diff='-    "react-leaflet": "4.2.1"\n+    "react-leaflet": "5.0.0"')
    violations = engine.check([action])
    assert len(violations) >= 1

# === 모순 X (5개) — 감지하면 안 됨 ===

def test_css_change_no_violation(engine):
    action = Action(type="modify", target="styles/app.css",
                    diff="+.header { color: red; }")
    violations = engine.check([action])
    assert len(violations) == 0

def test_other_library_no_violation(engine):
    action = Action(type="modify", target="package.json",
                    diff='+    "axios": "1.6.0"')
    violations = engine.check([action])
    assert len(violations) == 0

def test_principle_not_explicit_rule(engine):
    """'테스트 먼저'는 soft 원칙 → hard 규칙 아니므로 미등록"""
    # 이 규칙은 engine에 등록되지 않음 (strength != hard)
    action = Action(type="add", target="feature.py", diff="+def new_feature(): pass")
    violations = engine.check([action])
    assert len(violations) == 0

def test_principle_conflict_out_of_scope(engine):
    """원칙 vs 원칙 충돌은 범위 밖"""
    action = Action(type="modify", target="utils.py",
                    diff="+# readable but slower\ndef process(): ...")
    violations = engine.check([action])
    assert len(violations) == 0

def test_variable_not_violation(engine):
    """모델 이름 변수화는 위반 아님"""
    action = Action(type="modify", target="config.py",
                    diff='+MODEL = os.getenv("MODEL", "llama")')
    violations = engine.check([action])
    assert len(violations) == 0
```

**메트릭 검증:**
```python
def test_precision_recall():
    """전체 10개 테스트셋 기반 P/R 검증"""
    # true positives: 5개 중 감지된 수
    # false positives: 5개 중 잘못 감지된 수
    tp, fn, fp = 0, 0, 0
    # ... 위 10개 테스트 결과 집계
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    assert precision >= 0.9
    assert recall >= 0.7
```

---

## 6. 오픈소스 배포 준비

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "graphmem"
version = "0.1.0"
description = "Contradiction detection layer for AI agents"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [{ name = "superdog" }]
keywords = ["ai", "agent", "contradiction", "knowledge-graph", "memory"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Topic :: Software Development :: Libraries",
]
dependencies = [
    "kuzu>=0.4.0",
    "typer>=0.9.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.3.0"]

[project.scripts]
graphmem = "graphmem.cli:app"

[project.urls]
Homepage = "https://github.com/superdog/graphmem"
Repository = "https://github.com/superdog/graphmem"

[tool.ruff]
line-length = 100
target-version = "py310"
```

---

## 요약: 최소 실행 순서

```
Day 1: pyproject.toml + GitHub repo + Kuzu hello world
Day 2: models.py + store.py (스키마, CRUD)
Day 3: interfaces.py + memory_md.py (규칙 추출)
Day 4: engine.py + matchers (모순 감지 핵심)
Day 5: test_engine.py (10개 테스트 전부 통과)
Day 6: cli.py (init, check)
Day 7: file_change.py (git diff 디텍터)
Week 2: OpenClaw 통합 + README + PyPI 배포
```

핵심은 **Day 4-5** — `ContradictionEngine`과 `RuleMatcher`들이 10개 테스트를 통과하면 MVP 완성.
