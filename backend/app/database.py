"""数据库连接。

生产环境可通过 DATABASE_URL 指向 PostgreSQL；也可分别设置
DB_HOST、DB_PORT、DB_NAME、DB_USER、DB_PASSWORD，避免把凭据写入仓库。
本地开发/测试缺省使用 SQLite 文件，便于离线运行。
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL is None and os.getenv("DB_HOST"):
    from sqlalchemy import URL

    DATABASE_URL = str(
        URL.create(
            "postgresql+psycopg2",
            username=os.getenv("DB_USER", "distill"),
            password=os.environ["DB_PASSWORD"],
            host=os.environ["DB_HOST"],
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "distillation"),
        )
    )
if DATABASE_URL is None:
    DATABASE_URL = "sqlite:///./distillation.db"

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_schema() -> None:
    """建表 + 轻量迁移：为旧版 cut_schemes 补齐版本化列。

    未带版本状态的旧方案回填为可继续编辑的草稿（status=draft, revision=1）。
    生产环境建议改用 Alembic，本函数保证演示/培训环境平滑升级。
    """
    from . import models  # noqa: F401  确保所有表已注册到 metadata

    Base.metadata.create_all(bind=engine)
    dt_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP"
    with engine.begin() as conn:
        insp = inspect(conn)
        if "cut_schemes" not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns("cut_schemes")}
        if "status" not in cols:
            conn.execute(text("ALTER TABLE cut_schemes ADD COLUMN status VARCHAR(20)"))
        if "revision" not in cols:
            conn.execute(text("ALTER TABLE cut_schemes ADD COLUMN revision INTEGER"))
        if "updated_at" not in cols:
            conn.execute(text(f"ALTER TABLE cut_schemes ADD COLUMN updated_at {dt_type}"))
        if "active_version_id" not in cols:
            conn.execute(
                text("ALTER TABLE cut_schemes ADD COLUMN active_version_id INTEGER")
            )
        # 旧数据回填为可继续编辑的旧草稿
        conn.execute(text("UPDATE cut_schemes SET status='draft' WHERE status IS NULL"))
        conn.execute(text("UPDATE cut_schemes SET revision=1 WHERE revision IS NULL"))
        # 已有发布快照但无生效指针的方案：生效版本回填为最新快照
        conn.execute(
            text(
                """
                UPDATE cut_schemes SET active_version_id = (
                    SELECT MAX(sv.id) FROM scheme_versions sv
                    WHERE sv.scheme_id = cut_schemes.id
                )
                WHERE active_version_id IS NULL
                  AND EXISTS (
                      SELECT 1 FROM scheme_versions sv
                      WHERE sv.scheme_id = cut_schemes.id
                  )
                """
            )
        )
