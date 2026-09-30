"""数据库引擎 / 会话。

生产默认 PostgreSQL (DATABASE_URL)；测试与本地演示可用 SQLite。
JSON 使用通用 JSON 类型，避免在两处方言间迁移行为差异。
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite:///./milkfat.db"
)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=_connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
