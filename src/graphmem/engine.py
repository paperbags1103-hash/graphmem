from __future__ import annotations

import fnmatch
import re
from typing import Iterable

from .interfaces import RuleMatcher
from .models import Action, Rule, Violation
from .store import GraphStore


class ContradictionEngine:
    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.matchers: list[RuleMatcher] = [
            VersionPinMatcher(),
            ForbiddenCmdMatcher(),
            ValuePinMatcher(),
            SecretLeakMatcher(),
        ]

    def check(self, actions: list[Action]) -> list[Violation]:
        rules = self._load_rules()
        violations: list[Violation] = []

        for action in actions:
            action_id = self._store_action(action)
            for rule in self._relevant_rules(rules, action):
                for matcher in self.matchers:
                    violation = matcher.match(rule, action)
                    if violation is None:
                        continue
                    violations.append(violation)
                    self._store_violation(action_id, rule, violation)
                    break  # first matching matcher fires per rule

        return violations

    def _load_rules(self) -> list[Rule]:
        try:
            return list(self.store.get_rules(strength="hard"))
        except TypeError:
            return list(self.store.get_rules())

    def _store_action(self, action: Action) -> str | None:
        add_action = getattr(self.store, "add_action", None)
        if not callable(add_action):
            return None
        try:
            return add_action(action)
        except Exception:
            return None

    def _store_violation(
        self,
        action_id: str | None,
        rule: Rule,
        violation: Violation,
    ) -> None:
        """Persist violation to the graph store.

        FIX (Opus review #1): previously tried add_violation(action, rule, violation)
        which raised AttributeError (not TypeError), silently swallowed by except TypeError,
        so violations were never persisted. Now calls the correct signature directly.
        """
        if action_id is None:
            return
        add_violation = getattr(self.store, "add_violation", None)
        if not callable(add_violation):
            return
        try:
            add_violation(
                action_id,
                rule.id,
                violation.confidence,
                violation.reason,
            )
        except Exception:
            return

    def _relevant_rules(self, rules: Iterable[Rule], action: Action) -> list[Rule]:
        relevant: list[Rule] = []
        for rule in rules:
            patterns = [pattern for pattern in rule.target_files if pattern]
            if not patterns:
                relevant.append(rule)
                continue
            if any(fnmatch.fnmatch(action.target, pattern) for pattern in patterns):
                relevant.append(rule)
        return relevant


class BaseMatcher(RuleMatcher):
    KEYWORDS = ("금지", "고정", "절대", "must not", "never", "하지 말")

    @staticmethod
    def added_lines(diff: str) -> list[str]:
        lines: list[str] = []
        for raw_line in diff.splitlines():
            if raw_line.startswith(("+++", "@@")):
                continue
            if raw_line.startswith("+"):
                lines.append(raw_line[1:])
        return lines

    @staticmethod
    def removed_lines(diff: str) -> list[str]:
        lines: list[str] = []
        for raw_line in diff.splitlines():
            if raw_line.startswith(("---", "@@")):
                continue
            if raw_line.startswith("-"):
                lines.append(raw_line[1:])
        return lines

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def make_violation(rule: Rule, action: Action, confidence: float, reason: str) -> Violation:
        return Violation(rule=rule, action=action, confidence=confidence, reason=reason)


class VersionPinMatcher(BaseMatcher):
    # Matches versions like 4.2.0, v4.2.0, 5, 1.0.0-beta
    VERSION_RE = re.compile(r"v?\d+(?:\.\d+)*(?:[-+._][a-z0-9]+)?", re.IGNORECASE)
    # Captures package name before a version number.
    # FIX: allows optional quote/backtick between package name and version,
    # e.g. "`react-grid-layout` v1.4.4" — backtick after the name was
    # blocking the \s+ match, causing package_match = None → rule skipped.
    PACKAGE_RE = re.compile(
        r"([A-Za-z0-9_.@/-]+)['\"`]?\s+v?\d+(?:\.\d+)*(?:[-+._][a-z0-9]+)?",
        re.IGNORECASE,
    )

    def match(self, rule: Rule, action: Action) -> Violation | None:
        text = self.normalize(rule.content)
        if "고정" not in text and "pin" not in text and "fixed" not in text:
            return None

        # FIX (Opus review #2): extract version from near the package name, not just
        # the first number in the rule text (avoids e.g. "Python 3.11" grabbing "3"
        # and false-positiving on any diff with "3" in it).
        package_match = self.PACKAGE_RE.search(rule.content)
        if not package_match:
            return None

        package_name = package_match.group(1).strip("'\"`")
        # Find the version token that starts at or after the package match
        version_match = self.VERSION_RE.search(rule.content, package_match.start())
        if not version_match:
            return None
        pinned_version = version_match.group(0).lstrip("v")

        added = "\n".join(self.added_lines(action.diff))
        removed = "\n".join(self.removed_lines(action.diff))

        if package_name and package_name not in added and package_name not in removed:
            return None

        added_versions = {m.lstrip("v") for m in self.VERSION_RE.findall(added)}

        # Simplified condition (Opus review #2): just skip if no versions in diff
        if not added_versions:
            return None

        changed_to = next((v for v in added_versions if v != pinned_version), None)
        if changed_to is None:
            return None

        reason = f"Rule pins version {pinned_version}, but diff adds version {changed_to}."
        return self.make_violation(rule, action, 0.93, reason)


class ForbiddenCmdMatcher(BaseMatcher):
    COMMAND_RE = re.compile(
        r"(rm\s+-rf|curl\s+\|?\s*sh|chmod\s+777|sudo\s+rm|del\s+/f|format\s+[a-z]:)",
        re.IGNORECASE,
    )

    def match(self, rule: Rule, action: Action) -> Violation | None:
        text = self.normalize(rule.content)
        if not any(keyword in text for keyword in ("금지", "must not", "never", "하지 말")):
            return None

        candidate = self._extract_candidate(rule.content)
        if not candidate:
            return None

        for line in self.added_lines(action.diff):
            normalized_line = self.normalize(line)
            if candidate in normalized_line:
                reason = f"Rule forbids `{candidate}`, but the diff adds it."
                return self.make_violation(rule, action, 0.9, reason)
            command_match = self.COMMAND_RE.search(line)
            if command_match and candidate in self.normalize(command_match.group(0)):
                reason = f"Rule forbids `{candidate}`, but the diff adds it."
                return self.make_violation(rule, action, 0.92, reason)
        return None

    def _extract_candidate(self, content: str) -> str:
        quoted = re.findall(r"['\"`](.+?)['\"`]", content)
        if quoted:
            return self.normalize(max(quoted, key=len))

        match = self.COMMAND_RE.search(content)
        if match:
            return self.normalize(match.group(0))

        # FIX (Opus review #3): removed "last 3 tokens" fallback — it was a
        # false-positive factory (e.g. "debug mode 금지" → match any "debug mode"
        # substring in any diff). No clear candidate → skip this rule.
        return ""


class ValuePinMatcher(BaseMatcher):
    ASSIGNMENT_RE = re.compile(r"([A-Za-z_][\w.-]*)\s*[:=]\s*(['\"])(.*?)\2")

    def match(self, rule: Rule, action: Action) -> Violation | None:
        text = self.normalize(rule.content)
        if "고정" not in text and "fixed" not in text and "pin" not in text:
            return None

        rule_assignment = self.ASSIGNMENT_RE.search(rule.content)
        if not rule_assignment:
            return None

        key = rule_assignment.group(1)
        pinned_value = rule_assignment.group(3)

        added_assignments = self._find_assignments(self.added_lines(action.diff), key)
        new_value = next((value for value in added_assignments if value != pinned_value), None)
        if new_value is None:
            return None

        reason = f"Rule pins {key}={pinned_value!r}, but diff changes it to {new_value!r}."
        return self.make_violation(rule, action, 0.95, reason)

    def _find_assignments(self, lines: list[str], key: str) -> list[str]:
        values: list[str] = []
        for line in lines:
            for match in self.ASSIGNMENT_RE.finditer(line):
                if match.group(1) == key:
                    values.append(match.group(3))
        return values


class SecretLeakMatcher(BaseMatcher):
    SECRET_PATTERNS = {
        "openai": re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
        "aws": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "github": re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
        "slack": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    }
    GENERIC_SECRET_RE = re.compile(
        r"\b[A-Za-z_][\w-]*(?:API[_-]?KEY|SECRET)[\w-]*\b\s*[:=]\s*(['\"])(.{10,}?)\1",
        re.IGNORECASE,
    )

    def match(self, rule: Rule, action: Action) -> Violation | None:
        text = self.normalize(rule.content)
        if "하드코딩" not in text and "secret" not in text and "token" not in text:
            return None
        if not any(keyword in text for keyword in ("금지", "must not", "never", "하지 말")):
            return None

        for line in self.added_lines(action.diff):
            for label, pattern in self.SECRET_PATTERNS.items():
                if pattern.search(line):
                    reason = f"Rule forbids hardcoded secrets, but diff adds a suspected {label} secret."
                    return self.make_violation(rule, action, 0.99, reason)
            if self.GENERIC_SECRET_RE.search(line):
                reason = "Rule forbids hardcoded secrets, but diff adds a quoted API key or secret value."
                return self.make_violation(rule, action, 0.97, reason)
        return None
