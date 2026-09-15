"""导出：工作副本实时报告 + 已发布版本的冻结报告（JSON / CSV）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..database import get_db
from ..services.report import build_report, report_to_csv
from ..services.fractions import FractionInput
from .experiments import load_experiment

router = APIRouter(prefix="/api", tags=["export"])


@router.get("/experiments/{experiment_id}/schemes/{scheme_id}/export")
def export_scheme(
    experiment_id: int,
    scheme_id: int,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    """工作副本的实时导出（未冻结）：反映当前试验数据与当前切点。"""
    exp = load_experiment(db, experiment_id)
    scheme = (
        db.query(models.CutScheme)
        .options(selectinload(models.CutScheme.cuts))
        .filter(
            models.CutScheme.id == scheme_id,
            models.CutScheme.experiment_id == experiment_id,
        )
        .first()
    )
    if scheme is None:
        raise HTTPException(status_code=404, detail="方案不存在")
    fractions = [FractionInput(c.label, c.start_pct, c.end_pct) for c in scheme.cuts]
    report = build_report(
        exp,
        scheme_id=scheme.id,
        scheme_name=scheme.name,
        fractions=fractions,
        frozen=False,
    )
    report["scheme"]["status"] = scheme.current_status
    if format == "json":
        return report
    return PlainTextResponse(report_to_csv(report), media_type="text/csv; charset=utf-8")


@router.get("/scheme-versions/{version_id}/export")
def export_version(
    version_id: int,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    """已发布版本的冻结导出：直接读取发布时的快照，绝不重新计算。"""
    version = (
        db.query(models.SchemeVersion)
        .filter(models.SchemeVersion.id == version_id)
        .first()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    report = version.report_json
    if format == "json":
        return report
    return PlainTextResponse(report_to_csv(report), media_type="text/csv; charset=utf-8")
