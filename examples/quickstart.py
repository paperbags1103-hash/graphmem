from __future__ import annotations

from graphmem import GraphMem


def main() -> None:
    gm = GraphMem()
    gm.init(memory_path="MEMORY.md")
    violations = gm.scan()

    for violation in violations:
        print(violation)


if __name__ == "__main__":
    main()
