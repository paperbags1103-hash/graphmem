from __future__ import annotations

import re
from pathlib import Path

from ..interfaces import RuleSource
from ..models import Rule, Strength


class MemoryMdSource(RuleSource):
    RULE_KEYWORDS = ("절대", "금지", "고정", "never", "must not", "하지 말")
    FILE_PATTERN = re.compile(
        r"\b(?:[\w.-]+\/)*[\w.-]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|toml|ini|cfg|env|md)\b|\bvite\.config\.[\w*]+\b|\*\.[A-Za-z0-9]+\b"
    )

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path

    def extract(self) -> list[Rule]:
        path = Path(self.file_path)
        lines = path.read_text(encoding="utf-8").splitlines()

        rules: list[Rule] = []
        for index, line in enumerate(lines, start=1):
            if not self._looks_like_rule(line):
                continue

            target_files = self._extract_target_files(lines, index - 1)
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
            rules.append(rule)
        return rules

    def interactive_review(self, rules: list[Rule]) -> list[Rule]:
        approved: list[Rule] = []
        for rule in rules:
            print(f"[{rule.id}] {rule.content}")
            if rule.target_files:
                print(f"  target_files={rule.target_files}")
            answer = input("Keep rule? [y]es/[n]o/[e]dit: ").strip().lower()
            if answer == "n":
                continue
            if answer == "e":
                new_content = input("New content: ").strip()
                if new_content:
                    rule.content = new_content
                    rule.pattern = self._extract_pattern(new_content)
            approved.append(rule)
        return approved

    def _looks_like_rule(self, line: str) -> bool:
        lowered = line.lower()
        return any(keyword in lowered for keyword in self.RULE_KEYWORDS)

    def _extract_target_files(self, lines: list[str], index: int) -> list[str]:
        direct_matches = self.FILE_PATTERN.findall(lines[index])
        if direct_matches:
            return list(dict.fromkeys(direct_matches))

        contexts = [
            lines[index - 1] if index - 1 >= 0 and lines[index - 1].startswith("#") else "",
            lines[index - 2] if index - 2 >= 0 and lines[index - 1].startswith("#") else "",
        ]

        seen: list[str] = []
        for context in contexts:
            for match in self.FILE_PATTERN.findall(context):
                if match not in seen:
                    seen.append(match)
        return seen

    def _extract_pattern(self, content: str) -> str:
        quoted = re.findall(r"['\"`](.+?)['\"`]", content)
        if quoted:
            return max(quoted, key=len)

        assignment = re.search(r"([A-Za-z_][\w.-]*\s*[:=]\s*['\"].+?['\"])", content)
        if assignment:
            return assignment.group(1)

        return content.strip()
