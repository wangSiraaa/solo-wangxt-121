"""实时分析：插值查询与切割分析（不落库）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import assembly
from ..services.fractions import FractionInput
from ..services.interpolation import NonMonotonicError, OutOfRangeError
from .experiments import load_experiment

router = APIRouter(prefix="/api/experiments/{experiment_id}", tags=["analysis"])


@router.post("/interpolate")
def interpolate(
    experiment_id: int,
    payload: schemas.InterpolateRequest,
    db: Session = Depends(get_db),
):
    """单点插值查询。超出数据范围返回 422，绝不外推。"""
    exp = load_experiment(db, experiment_id)
    try:
        curve = assembly.build_curve(exp)
    except (ValueError, NonMonotonicError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        if payload.recovery_pct is not None:
            return {
                "recovery_pct": payload.recovery_pct,
                "temperature_c": curve.temperature_at(payload.recovery_pct),
                "interpolation": assembly.interpolation_meta(curve),
            }
        return {
            "temperature_c": payload.temperature_c,
            "recovery_pct": curve.recovery_at(payload.temperature_c),
            "interpolation": assembly.interpolation_meta(curve),
        }
    except OutOfRangeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except NonMonotonicError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/analyze")
def analyze(
    experiment_id: int,
    payload: schemas.AnalyzeRequest,
    db: Session = Depends(get_db),
):
    """实时分析（不保存）：前端调整切点时反复调用。"""
    exp = load_experiment(db, experiment_id)
    fractions = [FractionInput(f.label, f.start_pct, f.end_pct) for f in payload.fractions]
    result = assembly.run_analysis(exp, fractions)
    out = result.as_dict()
    out["interpolation"] = assembly.interpolation_meta(assembly.build_curve(exp))
    return out
