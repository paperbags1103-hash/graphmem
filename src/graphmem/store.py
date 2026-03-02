from __future__ import annotations

from uuid import uuid4

from .models import Action, Rule, Strength
from .schema import GraphStore as SchemaGraphStore


class GraphStore(SchemaGraphStore):
    def add_rule(self, rule: Rule) -> None:
        query = (
            f"MERGE (r:Rule {{id: {self._string(rule.id)}}}) "
            f"SET r.content = {self._string(rule.content)}, "
            f"r.strength = {self._string(rule.strength.value)}, "
            f"r.scope = {self._string(rule.scope)}, "
            f"r.source_file = {self._string(rule.source_file)}, "
            f"r.source_line = {self._int(rule.source_line)}, "
            f"r.pattern = {self._string(rule.pattern)}"
        )
        self._execute(query)

        for path in rule.target_files:
            self._execute(f"MERGE (f:File {{path: {self._string(path)}}})")

    def get_rules(self, strength: str = "hard") -> list[Rule]:
        query = (
            "MATCH (r:Rule) "
            "RETURN r.id, r.content, r.strength, r.scope, r.source_file, r.source_line, r.pattern "
            "ORDER BY r.id"
        )
        rows = self._rows(self._execute(query))

        rules: list[Rule] = []
        for row in rows:
            values = self._normalize_row(row)
            if len(values) < 7:
                continue

            rule_strength = str(values[2] or Strength.HARD.value)
            if strength and rule_strength != strength:
                continue

            scope = str(values[3] or "")
            rules.append(
                Rule(
                    id=str(values[0]),
                    content=str(values[1]),
                    strength=Strength(rule_strength),
                    scope=scope,
                    source_file=str(values[4] or ""),
                    source_line=int(values[5] or 0),
                    pattern=str(values[6] or ""),
                    target_files=[scope] if scope else [],
                )
            )
        return rules

    def add_action(self, action: Action) -> str:
        action_id = str(uuid4())
        query = (
            f"CREATE (a:ActionNode {{"
            f"id: {self._string(action_id)}, "
            f"type: {self._string(action.type)}, "
            f"target: {self._string(action.target)}, "
            f"agent: {self._string(action.agent)}, "
            f"ts: {self._string(action.timestamp.isoformat())}"
            f"}})"
        )
        self._execute(query)
        self._execute(f"MERGE (f:File {{path: {self._string(action.target)}}})")
        return action_id

    def add_violation(
        self,
        action_id: str,
        rule_id: str,
        confidence: float,
        reason: str,
    ) -> None:
        violation_id = str(uuid4())
        query = (
            f"CREATE (v:Violation {{"
            f"id: {self._string(violation_id)}, "
            f"rule_id: {self._string(rule_id)}, "
            f"action_id: {self._string(action_id)}, "
            f"confidence: {self._float(confidence)}, "
            f"reason: {self._string(reason)}"
            f"}})"
        )
        self._execute(query)

    def get_violations(self, limit: int = 50) -> list[dict]:
        query = (
            "MATCH (v:Violation) "
            "RETURN v.id, v.rule_id, v.action_id, v.confidence, v.reason "
            f"ORDER BY v.id DESC LIMIT {self._int(limit)}"
        )
        rows = self._rows(self._execute(query))

        violations: list[dict] = []
        for row in rows:
            values = self._normalize_row(row)
            if len(values) < 5:
                continue
            violations.append(
                {
                    "id": str(values[0]),
                    "rule_id": str(values[1]),
                    "action_id": str(values[2]),
                    "confidence": float(values[3]),
                    "reason": str(values[4]),
                }
            )
        return violations

    @staticmethod
    def _normalize_row(row: object) -> tuple:
        if isinstance(row, tuple):
            return row
        if isinstance(row, list):
            return tuple(row)
        if hasattr(row, "values"):
            values = row.values
            return tuple(values() if callable(values) else values)
        if hasattr(row, "__iter__") and not isinstance(row, (str, bytes)):
            return tuple(row)
        return (row,)
