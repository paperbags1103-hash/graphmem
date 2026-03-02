from __future__ import annotations

from datetime import datetime

from git import NULL_TREE, Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError

from ..interfaces import ActionDetector
from ..models import Action


class GitDiffDetector(ActionDetector):
    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = repo_path
        try:
            self.repo = Repo(repo_path, search_parent_directories=True)
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            raise ValueError(f"Not a git repository: {repo_path}") from exc

    def detect(self, n_commits: int = 1) -> list[Action]:
        actions: list[Action] = []
        commits = list(self.repo.iter_commits(max_count=n_commits))

        for commit in commits:
            parents = commit.parents or [None]
            for parent in parents:
                diff_index = (
                    parent.diff(commit, create_patch=True)
                    if parent is not None
                    else commit.diff(NULL_TREE, create_patch=True)
                )
                for diff in diff_index:
                    patch = self._decode(diff.diff)
                    target = diff.b_path or diff.a_path or ""
                    if not target:
                        continue
                    actions.append(
                        Action(
                            type=self._diff_type(diff),
                            target=target,
                            agent="git",
                            timestamp=datetime.fromtimestamp(commit.committed_date),
                            diff=patch,
                        )
                    )
        return actions

    def detect_staged(self) -> list[Action]:
        actions: list[Action] = []
        for diff in self.repo.index.diff("HEAD", create_patch=True):
            target = diff.b_path or diff.a_path or ""
            if not target:
                continue
            actions.append(
                Action(
                    type=self._diff_type(diff),
                    target=target,
                    agent="git:staged",
                    diff=self._decode(diff.diff),
                )
            )
        return actions

    @staticmethod
    def _decode(payload: bytes | str) -> str:
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return payload

    @staticmethod
    def _diff_type(diff: object) -> str:
        if getattr(diff, "new_file", False):
            return "add"
        if getattr(diff, "deleted_file", False):
            return "delete"
        if getattr(diff, "renamed_file", False):
            return "rename"
        return "modify"
