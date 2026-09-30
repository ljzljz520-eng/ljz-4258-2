#!/usr/bin/env python3
"""迁移运行器。

PostgreSQL：按顺序执行 migrations/*.sql（幂等，可重复运行）。
SQLite：使用 SQLAlchemy create_all（仅用于本地/测试，生产请用 PostgreSQL）。
用法：python -m scripts.migrate
"""
from __future__ import annotations

import pathlib
import re
import sys

from sqlalchemy import text

from app.database import DATABASE_URL, engine


def _split_sql(script: str) -> list[str]:
    # 迁移文件中的语句都以分号+换行结束，函数/触发器场景在 0001 中不存在
    stmts = []
    for chunk in re.split(r";\s*\n", script):
        c = chunk.strip()
        if c and not c.upper().startswith("BEGIN") and c.upper() != "COMMIT":
            stmts.append(c)
    return stmts


def main() -> int:
    root = pathlib.Path(__file__).resolve().parent.parent / "migrations"
    if DATABASE_URL.startswith("sqlite"):
        from app.database import Base
        import app.models  # noqa: F401  (register mappers)
        Base.metadata.create_all(bind=engine)
        print("sqlite: schema created via metadata")
        return 0
    files = sorted(root.glob("*.sql"))
    with engine.begin() as conn:
        for f in files:
            script = f.read_text(encoding="utf-8")
            for stmt in _split_sql(script):
                conn.execute(text(stmt))
            print(f"applied {f.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
