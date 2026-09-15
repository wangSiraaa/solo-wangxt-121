"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import ensure_schema
from .routers import analysis, experiments, export, schemes
from .services.versioning import ConflictError, InvalidTransitionError


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表 + 旧数据轻量迁移；生产环境建议使用 Alembic
    ensure_schema()
    yield


app = FastAPI(
    title="馏分切割方案工具（离线试验数据）",
    description=(
        "基于累积蒸馏曲线选择馏分切点并核对产率，方案支持草稿-审核-发布版本化。"
        "仅处理离线试验数据，不连接、不控制任何真实装置。"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Idempotent-Replay"],
)


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError):
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(exc),
            "code": "REVISION_CONFLICT",
            "current_revision": exc.current_revision,
        },
    )


@app.exception_handler(InvalidTransitionError)
async def invalid_transition_handler(request: Request, exc: InvalidTransitionError):
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "code": "INVALID_TRANSITION"},
    )


app.include_router(experiments.router)
app.include_router(analysis.router)
app.include_router(schemes.router)
app.include_router(export.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
