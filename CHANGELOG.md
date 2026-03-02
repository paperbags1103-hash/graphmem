# Changelog

## v0.1.0 (2026-03-02)

First release of graphmem — AI Agent Ontology Memory Layer.

### Features
- **ContradictionEngine** with 4 matchers:
  - `VersionPinMatcher` — detects version changes that violate pinned versions
  - `ValuePinMatcher` — detects config value changes (e.g. `base: './'`)
  - `ForbiddenCmdMatcher` — detects forbidden commands in shell/CI files
  - `SecretLeakMatcher` — detects hardcoded API keys and secrets
- **MemoryMdSource** — extracts hard rules from MEMORY.md (and any markdown file)
  - Section header filtering (headings with keywords are skipped)
  - File scope inference (8 heuristic patterns: shell → `*.sh`, vite → `vite.config.*`, etc.)
  - LLM-assisted classification (opt-in, `pip install 'graphmem[llm]'`)
- **GraphStore** — Kuzu embedded graph DB (no server, file-based)
- **CLI**: `graphmem init`, `scan`, `check`, `status`, `install-hook`, `uninstall-hook`
- **Pre-commit hook** — blocks commits with rule violations (`graphmem install-hook`)
- **GitHub Action** — CI integration (`.github/workflows/graphmem.yml`)
- **Confidence threshold** — `--threshold 0.85` (default), tunable per scan
- **Test suite** — 18 tests (10 unit + 8 integration)

### Design
- Precision ≥ 90%, Recall ≥ 70% — false positives are worse than false negatives
- Embedded DB (Kuzu) — `pip install graphmem` one-liner, no infrastructure
- Rule sources: MEMORY.md, AGENTS.md, CONTRIBUTING.md, ADR docs — any markdown file

### Known Limitations
- AI behavior rules (e.g. "always respond in Korean") require `--extract-model` LLM filter
- Single Kuzu connection — no concurrent scans on the same DB
- Positive constraints ("always use TypeScript strict") not supported (only explicit prohibitions)
