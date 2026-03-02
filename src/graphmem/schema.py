from __future__ import annotations

from pathlib import Path
from typing import Any

import kuzu


class GraphStore:
    def __init__(self, db_path: str = ".graphmem/db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = kuzu.Database(db_path)
        self.conn = kuzu.Connection(self.db)
        self._init_schema()

    def _init_schema(self) -> None:
        ddl = [
            (
                "CREATE NODE TABLE IF NOT EXISTS Rule("
                "id STRING, content STRING, strength STRING, scope STRING, "
                "source_file STRING, source_line INT64, pattern STRING, PRIMARY KEY(id))"
            ),
            "CREATE NODE TABLE IF NOT EXISTS File(path STRING, PRIMARY KEY(path))",
            (
                "CREATE NODE TABLE IF NOT EXISTS ActionNode("
                "id STRING, type STRING, target STRING, agent STRING, ts STRING, PRIMARY KEY(id))"
            ),
            (
                "CREATE NODE TABLE IF NOT EXISTS Violation("
                "id STRING, rule_id STRING, action_id STRING, confidence DOUBLE, reason STRING, "
                "PRIMARY KEY(id))"
            ),
        ]
        for statement in ddl:
            self.conn.execute(statement)

    @staticmethod
    def _quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    @classmethod
    def _string(cls, value: str) -> str:
        return cls._quote(value or "")

    @staticmethod
    def _int(value: int) -> str:
        return str(int(value))

    @staticmethod
    def _float(value: float) -> str:
        return repr(float(value))

    def _execute(self, query: str) -> Any:
        return self.conn.execute(query)

    def _rows(self, result: Any) -> list[Any]:
        if result is None:
            return []

        if hasattr(result, "get_as_df"):
            df = result.get_as_df()
            if hasattr(df, "itertuples"):
                return list(df.itertuples(index=False, name=None))
            return []

        if hasattr(result, "fetch_as_df"):
            df = result.fetch_as_df()
            if hasattr(df, "itertuples"):
                return list(df.itertuples(index=False, name=None))
            return []

        if hasattr(result, "has_next") and hasattr(result, "get_next"):
            rows: list[Any] = []
            while result.has_next():
                rows.append(result.get_next())
            return rows

        if hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
            return list(result)

        return []
