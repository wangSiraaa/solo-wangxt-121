"""试验管理：创建、查询、曲线校验信息。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from .. import models, schemas
from ..services import assembly
from ..services.interpolation import NonMonotonicError

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def load_experiment(db: Session, experiment_id: int) -> models.Experiment:
    exp = (
        db.query(models.Experiment)
        .options(
            selectinload(models.Experiment.points),
            selectinload(models.Experiment.densities),
        )
        .filter(models.Experiment.id == experiment_id)
        .first()
    )
    if exp is None:
        raise HTTPException(status_code=404, detail="试验不存在")
    return exp


@router.post("", response_model=schemas.ExperimentDetail, status_code=201)
def create_experiment(payload: schemas.ExperimentIn, db: Session = Depends(get_db)):
    exp = models.Experiment(
        name=payload.name,
        sample=payload.sample,
        method=payload.method,
        curve_basis=payload.curve_basis,
        pressure_kpa=payload.pressure_kpa,
        operator=payload.operator,
        defined_total_pct=payload.defined_total_pct,
        notes=payload.notes,
        points=[
            models.CurvePoint(recovery_pct=p.recovery_pct, temperature_c=p.temperature_c)
            for p in payload.points
        ],
        densities=[
            models.FractionDensity(
                label=d.label,
                start_pct=d.start_pct,
                end_pct=d.end_pct,
                density_kg_m3=d.density_kg_m3,
            )
            for d in payload.densities
        ],
    )
    # 先校验曲线，error 级问题拒绝入库
    pts = sorted((p.recovery_pct, p.temperature_c) for p in exp.points)
    issues = assembly.validate_curve(pts)
    if any(i.severity == "error" for i in issues):
        raise HTTPException(
            status_code=422,
            detail={"message": "曲线数据存在错误，未保存", "issues": [i.as_dict() for i in issues]},
        )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return _detail(exp)


@router.get("", response_model=list[schemas.ExperimentSummary])
def list_experiments(db: Session = Depends(get_db)):
    exps = db.query(models.Experiment).order_by(models.Experiment.id).all()
    return [
        schemas.ExperimentSummary(
            id=e.id,
            name=e.name,
            sample=e.sample,
            method=e.method,
            curve_basis=e.curve_basis,
            created_at=e.created_at.isoformat(),
        )
        for e in exps
    ]


@router.get("/{experiment_id}", response_model=schemas.ExperimentDetail)
def get_experiment(experiment_id: int, db: Session = Depends(get_db)):
    return _detail(load_experiment(db, experiment_id))


@router.put("/{experiment_id}", response_model=schemas.ExperimentDetail)
def update_experiment(
    experiment_id: int, payload: schemas.ExperimentIn, db: Session = Depends(get_db)
):
    """更新试验条件/曲线/密度。

    注意：已发布的方案版本在发布时已冻结快照，此处修改不会改写历史报告。
    """
    exp = load_experiment(db, experiment_id)
    pts = sorted((p.recovery_pct, p.temperature_c) for p in payload.points)
    issues = assembly.validate_curve(pts)
    if any(i.severity == "error" for i in issues):
        raise HTTPException(
            status_code=422,
            detail={"message": "曲线数据存在错误，未保存", "issues": [i.as_dict() for i in issues]},
        )
    exp.name = payload.name
    exp.sample = payload.sample
    exp.method = payload.method
    exp.curve_basis = payload.curve_basis
    exp.pressure_kpa = payload.pressure_kpa
    exp.operator = payload.operator
    exp.defined_total_pct = payload.defined_total_pct
    exp.notes = payload.notes
    exp.points = [
        models.CurvePoint(recovery_pct=p.recovery_pct, temperature_c=p.temperature_c)
        for p in payload.points
    ]
    exp.densities = [
        models.FractionDensity(
            label=d.label, start_pct=d.start_pct, end_pct=d.end_pct,
            density_kg_m3=d.density_kg_m3,
        )
        for d in payload.densities
    ]
    db.commit()
    db.refresh(exp)
    return _detail(exp)


def _detail(exp: models.Experiment) -> schemas.ExperimentDetail:
    issues = assembly.curve_issues(exp)
    try:
        meta = assembly.interpolation_meta(assembly.build_curve(exp))
    except (ValueError, NonMonotonicError) as exc:
        meta = {"error": str(exc)}
    return schemas.ExperimentDetail(
        id=exp.id,
        name=exp.name,
        sample=exp.sample,
        method=exp.method,
        curve_basis=exp.curve_basis,
        pressure_kpa=exp.pressure_kpa,
        operator=exp.operator,
        defined_total_pct=exp.defined_total_pct,
        notes=exp.notes,
        points=[
            schemas.CurvePointOut(recovery_pct=r, temperature_c=t)
            for r, t in assembly.sorted_points(exp)
        ],
        densities=[
            schemas.FractionDensityIn(
                label=d.label,
                start_pct=d.start_pct,
                end_pct=d.end_pct,
                density_kg_m3=d.density_kg_m3,
            )
            for d in exp.densities
        ],
        curve_issues=[i.as_dict() for i in issues],
        interpolation=meta,
    )
