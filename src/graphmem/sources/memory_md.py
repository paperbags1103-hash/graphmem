from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..interfaces import RuleSource
from ..models import Rule, Strength


# ---------------------------------------------------------------------------
# File-scope inference table
# Each entry: (regex to match against rule content, list of file glob patterns)
# Ordered from most specific to most general.
# ---------------------------------------------------------------------------
_SCOPE_TABLE: list[tuple[re.Pattern[str], list[str]]] = [
    # Explicit shell-command danger patterns — scope to shell/CI files only
    (
        re.compile(r"\b(rm\s*-rf|curl\s*\|?\s*sh|chmod\s+777|sudo\s+rm|wget\s+\|?\s*sh)\b", re.IGNORECASE),
        ["*.sh", "*.bash", "Makefile", ".github/**"],
    ),
    # General "open 명령 / 브라우저" — shell/CI only
    # Pattern allows backticks/quotes between `open` and the keyword
    (
        re.compile(r"\bopen\b.{0,10}(명령|command|브라우저|browser)", re.IGNORECASE),
        ["*.sh", "*.bash", "Makefile", ".github/**"],
    ),
    # Vite / build config
    (
        re.compile(r"\b(vite|webpack|rollup|esbuild|parcel)\b", re.IGNORECASE),
        ["vite.config.*", "webpack.config.*", "rollup.config.*"],
    ),
    # npm / yarn / pnpm — package manifests
    (
        re.compile(r"\b(npm|yarn|pnpm|node_modules|package\.json)\b", re.IGNORECASE),
        ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
    ),
    # pip / poetry / pyproject — Python deps
    (
        re.compile(r"\b(pip|pyproject|requirements|setup\.py|poetry)\b", re.IGNORECASE),
        ["pyproject.toml", "requirements*.txt", "setup.py", "poetry.lock"],
    ),
    # Docker
    (
        re.compile(r"\b(docker|dockerfile|compose)\b", re.IGNORECASE),
        ["Dockerfile", "docker-compose*.yml", "docker-compose*.yaml"],
    ),
    # GitHub Actions / CI
    (
        re.compile(r"\b(github\s+actions?|\.github|workflow|\.yml\s+ci)\b", re.IGNORECASE),
        [".github/**", "*.yml", "*.yaml"],
    ),
    # Leaflet / React / JS library imports → JS/TS files
    (
        re.compile(r"\b(import|require|leaflet|react|vue|svelte)\b", re.IGNORECASE),
        ["*.ts", "*.tsx", "*.js", "*.jsx"],
    ),
]


@dataclass
class ExtractedRule:
    rule: Rule
    inferred_scope: bool = False
    rejected: bool = False
    rejection_reason: str = ""


class MemoryMdSource(RuleSource):
    RULE_KEYWORDS = ("절대", "금지", "고정", "never", "must not", "하지 말")
    FILE_PATTERN = re.compile(
        r"\b(?:[\w.-]+\/)*[\w.-]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|toml|ini|cfg|env|md)\b"
        r"|\bvite\.config\.[\w*]+\b"
        r"|\*\.[A-Za-z0-9]+\b"
    )
    # Section headings that contain keywords but aren't rules
    HEADER_RE = re.compile(r"^#{1,6}\s+|^={3,}|^-{3,}")

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self) -> list[Rule]:
        """Keyword-only extraction. Fast, no LLM required."""
        return [r.rule for r in self._extract_annotated()]

    def extract_annotated(self) -> list[ExtractedRule]:
        """Return ExtractedRule objects with scope-inference metadata."""
        return self._extract_annotated()

    def classify_with_llm(
        self, rules: list[Rule], model: str
    ) -> tuple[list[Rule], list[tuple[Rule, str]]]:
        """LLM-assisted classification. Requires `pip install 'graphmem[llm]'`.

        Returns:
            (kept_rules, [(rejected_rule, reason), ...])
        """
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "LLM extraction requires openai: pip install 'graphmem[llm]'"
            ) from exc

        api_key = os.getenv("GRAPHMEM_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("GRAPHMEM_LLM_BASE_URL")  # None = default OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)

        kept: list[Rule] = []
        rejected: list[tuple[Rule, str]] = []

        for rule in rules:
            label, reason = self._classify_one(client, model, rule.content)
            if label == "CODE_RULE":
                kept.append(rule)
            else:
                rejected.append((rule, reason))

        return kept, rejected

    def interactive_review(self, rules: list[Rule]) -> list[Rule]:
        approved: list[Rule] = []
        for rule in rules:
            print(f"\n[{rule.id}] {rule.content}")
            if rule.target_files:
                print(f"  scope: {', '.join(rule.target_files)}")
            answer = input("Keep? [y]es / [n]o / [e]dit: ").strip().lower()
            if answer == "n":
                continue
            if answer == "e":
                new_content = input("New content: ").strip()
                if new_content:
                    rule.content = new_content
                    rule.pattern = self._extract_pattern(new_content)
            approved.append(rule)
        return approved

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract_annotated(self) -> list[ExtractedRule]:
        path = Path(self.file_path)
        lines = path.read_text(encoding="utf-8").splitlines()

        results: list[ExtractedRule] = []
        for index, line in enumerate(lines, start=1):
            if not self._looks_like_rule(line):
                continue

            # Skip section headers (contain keywords but are headings)
            if self.HEADER_RE.match(line.strip()):
                continue

            target_files = self._extract_target_files(lines, index - 1)
            inferred = False

            if not target_files:
                content_raw = line.strip().lstrip("-*0123456789. ").strip()
                inferred_files = self._infer_scope(content_raw)
                if inferred_files:
                    target_files = inferred_files
                    inferred = True

            content = line.strip().lstrip("-*0123456789. ").strip()
            rule = Rule(
                id=f"{path.stem}:{index}",
                content=content,
                strength=Strength.HARD,
                scope=target_files[0] if target_files else "",
                source_file=str(path),
                source_line=index,
                pattern=self._extract_pattern(content),
                target_files=target_files,
            )
            results.append(ExtractedRule(rule=rule, inferred_scope=inferred))

        return results

    def _looks_like_rule(self, line: str) -> bool:
        lowered = line.lower()
        return any(keyword in lowered for keyword in self.RULE_KEYWORDS)

    def _extract_target_files(self, lines: list[str], index: int) -> list[str]:
        direct_matches = self.FILE_PATTERN.findall(lines[index])
        if direct_matches:
            return list(dict.fromkeys(direct_matches))

        # Look in the 1-2 lines above if they are headings
        contexts = [
            lines[index - 1] if index - 1 >= 0 and lines[index - 1].startswith("#") else "",
            lines[index - 2] if index - 2 >= 0 and lines[index - 2].startswith("#") else "",
        ]

        seen: list[str] = []
        for context in contexts:
            for match in self.FILE_PATTERN.findall(context):
                if match not in seen:
                    seen.append(match)
        return seen

    def _infer_scope(self, content: str) -> list[str]:
        """Infer file-scope patterns from rule content using keyword heuristics."""
        for pattern, file_patterns in _SCOPE_TABLE:
            if pattern.search(content):
                return file_patterns
        return []

    def _extract_pattern(self, content: str) -> str:
        quoted = re.findall(r"['\"`](.+?)['\"`]", content)
        if quoted:
            return max(quoted, key=len)

        assignment = re.search(r"([A-Za-z_][\w.-]*\s*[:=]\s*['\"].+?['\"])", content)
        if assignment:
            return assignment.group(1)

        return content.strip()

    @staticmethod
    def _classify_one(client: object, model: str, content: str) -> tuple[str, str]:
        """Ask LLM to classify a single rule line. Returns (label, reason)."""
        prompt = (
            f'Classify this line from a developer\'s notes. Answer with ONLY one word.\n\n'
            f'Line: "{content}"\n\n'
            f"Options:\n"
            f"- HEADER: section heading or title (not a rule, not actionable)\n"
            f"- BEHAVIOR: rule about AI assistant behavior, communication style, "
            f"or workflow — not verifiable by checking code/file changes\n"
            f"- CODE_RULE: constraint on code or config files that can be verified "
            f"by inspecting a git diff\n\n"
            f"Answer:"
        )
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0,
            )
            label = response.choices[0].message.content.strip().upper()
        except Exception:
            # On LLM error → fail open (keep the rule, prefer recall)
            return "CODE_RULE", ""

        if "CODE_RULE" in label:
            return "CODE_RULE", ""
        if "HEADER" in label:
            return "HEADER", "section header"
        return "BEHAVIOR", "AI behavior rule"
