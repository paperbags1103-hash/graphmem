"""Pre-commit hook installation and management for graphmem."""
from __future__ import annotations

import stat
from pathlib import Path

# The shell hook script installed into .git/hooks/pre-commit
_HOOK_BODY = """\
# --- graphmem pre-commit hook (do not remove this line) ---
# Scans staged changes for rule violations before committing.
# To bypass: git commit --no-verify
# To uninstall: graphmem uninstall-hook

_GRAPHMEM_MEMORY="${GRAPHMEM_MEMORY:-MEMORY.md}"

if ! command -v graphmem > /dev/null 2>&1; then
  echo "[graphmem] not installed — skipping. Run: pip install graphmem"
else
  if [ -f "$_GRAPHMEM_MEMORY" ]; then
    echo "[graphmem] checking staged changes against $_GRAPHMEM_MEMORY..."
    _GRAPHMEM_FAILED=0

    while IFS= read -r _file; do
      [ -z "$_file" ] && continue
      git diff --cached -- "$_file" | graphmem check "$_file" --memory "$_GRAPHMEM_MEMORY"
      _exit=$?
      [ "$_exit" -ne 0 ] && _GRAPHMEM_FAILED=1
    done < <(git diff --cached --name-only)

    if [ "$_GRAPHMEM_FAILED" -ne 0 ]; then
      echo ""
      echo "[graphmem] commit blocked — rule violation(s) detected."
      echo "[graphmem] fix the issue or bypass with: git commit --no-verify"
      exit 1
    fi
  fi
fi
# --- end graphmem ---
"""

_MARKER_START = "# --- graphmem pre-commit hook (do not remove this line) ---"
_MARKER_END = "# --- end graphmem ---"


def install(repo_path: str = ".") -> Path:
    """Install graphmem pre-commit hook. Appends to existing hook if present.

    Returns the path to the hook file.
    Raises FileNotFoundError if the repo has no .git directory.
    Raises RuntimeError if a graphmem hook is already installed.
    """
    git_dir = Path(repo_path) / ".git"
    if not git_dir.is_dir():
        raise FileNotFoundError(f"No .git directory found at '{repo_path}'")

    hook_path = git_dir / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    existing = hook_path.read_text(encoding="utf-8") if hook_path.exists() else ""

    if _MARKER_START in existing:
        raise RuntimeError("graphmem hook is already installed.")

    if existing and not existing.startswith("#"):
        raise RuntimeError(
            "Existing pre-commit hook is not a shell script. "
            "Please integrate graphmem manually."
        )

    shebang = "#!/usr/bin/env sh\n" if not existing else ""
    new_content = shebang + existing.rstrip() + ("\n\n" if existing else "") + _HOOK_BODY

    hook_path.write_text(new_content, encoding="utf-8")
    # Ensure executable
    mode = hook_path.stat().st_mode
    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return hook_path


def uninstall(repo_path: str = ".") -> bool:
    """Remove graphmem section from pre-commit hook.

    Returns True if the hook was found and removed, False if not installed.
    """
    hook_path = Path(repo_path) / ".git" / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False

    text = hook_path.read_text(encoding="utf-8")
    if _MARKER_START not in text:
        return False

    lines = text.splitlines(keepends=True)
    in_block = False
    filtered: list[str] = []
    for line in lines:
        if _MARKER_START in line:
            in_block = True
        if not in_block:
            filtered.append(line)
        if _MARKER_END in line:
            in_block = False

    new_content = "".join(filtered).rstrip()
    if new_content.strip() in ("", "#!/usr/bin/env sh"):
        hook_path.unlink()
    else:
        hook_path.write_text(new_content + "\n", encoding="utf-8")

    return True
