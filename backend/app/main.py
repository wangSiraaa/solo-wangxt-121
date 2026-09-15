"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import analysis, experiments, export


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 开发/演示环境直接建表；生产环境建议使用 Alembic 迁移
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="馏分切割方案工具（离线试验数据）",
    description=(
        "基于累积蒸馏曲线选择馏分切点并核对产率。"
        "仅处理离线试验数据，不连接、不控制任何真实装置。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(experiments.router)
app.include_router(analysis.router)
app.include_router(export.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
