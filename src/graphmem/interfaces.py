from __future__ import annotations

from abc import ABC, abstractmethod

from .models import Action, Rule, Violation


class RuleSource(ABC):
    @abstractmethod
    def extract(self) -> list[Rule]:
        raise NotImplementedError


class ActionDetector(ABC):
    @abstractmethod
    def detect(self) -> list[Action]:
        raise NotImplementedError


class RuleMatcher(ABC):
    @abstractmethod
    def match(self, rule: Rule, action: Action) -> Violation | None:
        raise NotImplementedError
