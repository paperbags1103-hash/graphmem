# graphmem

**AI Agent Ontology Memory Layer** — detect when agent actions violate rules stored in your memory files.

graphmem watches your git commits and alerts you when a code change contradicts an explicitly defined rule — version pins, forbidden commands, value constraints, secret leaks.

```
⚠️  위반 #1 (신뢰도 93%)
   규칙: react-grid-layout v1.4.4 고정
   출처: MEMORY.md:27
   이유: Rule pins version 1.4.4, but diff adds version 2.0.0.
   파일: package.json
```

---

## Install

```bash
pip install graphmem
```

With LLM-assisted rule extraction (recommended):

```bash
pip install 'graphmem[llm]'
```

Requires Python ≥ 3.10. Uses [Kuzu](https://kuzudb.com/) embedded graph DB — no server needed.

---

## Quick Start

**1. Extract rules from your MEMORY.md**

```bash
graphmem init --memory MEMORY.md --auto
```

graphmem scans for lines containing hard constraint keywords (`절대`, `금지`, `고정`, `never`, `must not`) and saves them to a local graph store.

With LLM classification (filters out section headers and AI-behavior rules):

```bash
export OPENAI_API_KEY=sk-...
graphmem init --memory MEMORY.md --extract-model gpt-4o-mini
```

**2. Scan your latest commit**

```bash
graphmem scan --repo . --memory MEMORY.md
```

**3. Check a single file**

```bash
git diff HEAD~1 HEAD -- package.json | graphmem check package.json --memory MEMORY.md
```

---

## What It Detects

| Matcher | Example rule | Example violation |
|---|---|---|
| **VersionPinMatcher** | `react-grid-layout v1.4.4 고정` | `package.json` adds `v2.0.0` |
| **ValuePinMatcher** | `Vite base: './' 고정` | `vite.config.ts` sets `base: '/app/'` |
| **ForbiddenCmdMatcher** | `rm -rf 절대 금지` | `deploy.sh` adds `rm -rf /tmp/build` |
| **SecretLeakMatcher** | `API 키 하드코딩 금지` | `api.ts` adds `sk-proj-xxxxx` |

**Design goals**: Precision ≥ 90%, Recall ≥ 70%. False positives are worse than false negatives — graphmem is conservative.

---

## File Scope Inference

graphmem automatically infers which files a rule applies to:

- Shell commands (`rm -rf`, `curl`, `chmod`) → `*.sh`, `Makefile`, `.github/**`
- Vite/webpack rules → `vite.config.*`, `webpack.config.*`
- npm/yarn rules → `package.json`, `package-lock.json`
- Python dep rules → `pyproject.toml`, `requirements*.txt`

Rules without an inferred scope apply to all changed files.

---

## CLI Reference

```bash
graphmem init   --memory MEMORY.md           # Extract rules
                --db .graphmem/db            # DB path (default)
                --auto                       # Skip interactive review
                --extract-model gpt-4o-mini  # LLM classification

graphmem scan   --repo .                     # Scan latest commit
                --memory MEMORY.md
                --commit HEAD                # Any commit ref
                --threshold 0.85             # Confidence threshold (default 0.85)
                --extract-model gpt-4o-mini  # LLM filter

graphmem check  package.json                 # Check one file (diff via stdin)
                --memory MEMORY.md
                --threshold 0.85

graphmem status --db .graphmem/db            # Show rule/violation counts
```

---

## LLM Extraction

Without LLM, keyword-only extraction may include:
- Section headers: `### 기술 스택 (절대 바꾸지 말 것)` — contains `절대`
- AI behavior rules: `Discord 답변 시 테이블 금지` — not verifiable in code

With `--extract-model`, graphmem asks an LLM to classify each candidate as:
- `CODE_RULE` → kept (verifiable against file changes)
- `BEHAVIOR` → rejected (AI assistant rules)
- `HEADER` → rejected (section headings)

Any OpenAI-compatible provider works:

```bash
# OpenAI
export OPENAI_API_KEY=sk-...
graphmem init --extract-model gpt-4o-mini

# Other providers (OpenRouter, local Ollama, etc.)
export GRAPHMEM_LLM_BASE_URL=http://localhost:11434/v1
export GRAPHMEM_LLM_API_KEY=ollama
graphmem init --extract-model llama3.2
```

---

## Confidence Threshold

Control false positive rate with `--threshold`:

```bash
graphmem scan --threshold 0.90   # strict — fewer alerts
graphmem scan --threshold 0.70   # relaxed — more alerts
```

Default: `0.85`.

---

## CI Integration — GitHub Action

Add to `.github/workflows/graphmem.yml`:

```yaml
name: graphmem rule scan
on: [push, pull_request]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: {fetch-depth: 2}
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install graphmem
      - run: graphmem scan --memory MEMORY.md
```

graphmem will fail the CI check (`exit 1`) when violations are found, blocking the merge.

---

## Pre-commit Hook

Catch violations at the source — before the commit reaches remote:

```bash
# Install into current repo
graphmem install-hook

# Bypass for a specific commit
git commit --no-verify

# Remove hook
graphmem uninstall-hook
```

The hook pipes each staged file's diff through `graphmem check` and blocks the commit if violations are found.

---

## Rule Sources

graphmem works with any markdown file that contains hard constraint keywords.
Pass any of these as `--memory`:

```bash
graphmem scan --memory MEMORY.md         # AI assistant long-term memory
graphmem scan --memory AGENTS.md         # Agent operating rules
graphmem scan --memory CONTRIBUTING.md   # Team contribution rules
graphmem scan --memory ADR/decisions.md  # Architecture Decision Records
```

Combine multiple rule files by running `graphmem init` for each:

```bash
graphmem init --memory MEMORY.md --auto
graphmem init --memory AGENTS.md --auto
graphmem scan --memory MEMORY.md  # picks up rules from all previously init'd sources
```

---

## How It Works

```
MEMORY.md
  ↓ keyword extraction (+ optional LLM classification)
Rules (Kuzu graph DB)
  ↓
git diff (latest commit)
  ↓ per-file actions
ContradictionEngine
  ├── VersionPinMatcher
  ├── ValuePinMatcher
  ├── ForbiddenCmdMatcher
  └── SecretLeakMatcher
  ↓
Violations → console output
```

Rules and violations are stored in a [Kuzu](https://kuzudb.com/) embedded graph database at `.graphmem/db` (local, no server).

---

## Programmatic API

```python
from graphmem.sources.memory_md import MemoryMdSource
from graphmem.store import GraphStore
from graphmem.engine import ContradictionEngine
from graphmem.models import Action

# Extract rules
source = MemoryMdSource("MEMORY.md")
rules = source.extract()

# Store
store = GraphStore(db_path=".graphmem/db")
for rule in rules:
    store.add_rule(rule)

# Detect violations
engine = ContradictionEngine(store)
action = Action(
    type="git_commit",
    target="package.json",
    diff='+ "react-grid-layout": "2.0.0"',
)
violations = engine.check([action])

for v in violations:
    print(f"{v.confidence:.0%} — {v.rule.content}")
    print(f"  {v.reason}")
```

---

## Supported Rule Keywords

graphmem looks for these keywords (Korean + English):

| Korean | English |
|---|---|
| 절대 | never |
| 금지 | must not |
| 고정 | pin / fixed |
| 하지 말 | — |

---

## License

MIT
