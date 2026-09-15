"""导出：切割方案报告（JSON / CSV），含插值方法与适用范围。"""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session, selectinload

from .. import models
from ..database import get_db
from ..services import assembly
from ..services.fractions import FractionInput
from .experiments import load_experiment

router = APIRouter(prefix="/api/experiments/{experiment_id}/schemes", tags=["export"])

BASIS_LABEL = {"volume": "体积%", "mass": "质量%"}


def _load_scheme(db: Session, experiment_id: int, scheme_id: int) -> models.CutScheme:
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
    return scheme


def _report(exp: models.Experiment, scheme: models.CutScheme) -> dict:
    fractions = [FractionInput(c.label, c.start_pct, c.end_pct) for c in scheme.cuts]
    analysis = assembly.run_analysis(exp, fractions)
    curve = assembly.build_curve(exp)
    return {
        "report": "馏分切割方案报告",
        "experiment": {
            "id": exp.id,
            "name": exp.name,
            "sample": exp.sample,
            "method": exp.method,
            "curve_basis": exp.curve_basis,
            "curve_basis_label": BASIS_LABEL.get(exp.curve_basis, exp.curve_basis),
            "pressure_kpa": exp.pressure_kpa,
            "operator": exp.operator,
            "defined_total_pct": exp.defined_total_pct,
            "notes": exp.notes,
        },
        "scheme": {"id": scheme.id, "name": scheme.name},
        "interpolation": assembly.interpolation_meta(curve),
        "curve_points": [
            {"recovery_pct": r, "temperature_c": t} for r, t in assembly.sorted_points(exp)
        ],
        "curve_issues": [i.as_dict() for i in assembly.curve_issues(exp)],
        "analysis": analysis.as_dict(),
        "disclaimer": (
            "本报告基于离线试验数据，插值仅在数据覆盖范围内有效，不外推："
            "未对高温端或低温端做任何外推；质量%与体积%通过实测密度换算，不可混用。"
        ),
    }


@router.get("/{scheme_id}/export")
def export_scheme(
    experiment_id: int,
    scheme_id: int,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
):
    exp = load_experiment(db, experiment_id)
    scheme = _load_scheme(db, experiment_id, scheme_id)
    report = _report(exp, scheme)
    if format == "json":
        return report
    return PlainTextResponse(_to_csv(report), media_type="text/csv; charset=utf-8")


def _to_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    exp = report["experiment"]
    interp = report["interpolation"]
    rng = interp["applicable_range"]
    ana = report["analysis"]

    w.writerow(["# 馏分切割方案报告"])
    w.writerow(["# 试验", exp["name"]])
    w.writerow(["# 样品", exp["sample"]])
    w.writerow(["# 方法", exp["method"]])
    w.writerow(["# 曲线基准", exp["curve_basis_label"]])
    w.writerow(["# 方案", report["scheme"]["name"]])
    w.writerow(["# 插值方法", interp["method"]])
    w.writerow(["# 插值说明", interp["description"]])
    w.writerow(
        ["# 适用范围-回收率%", rng["recovery_min_pct"], rng["recovery_max_pct"]]
    )
    w.writerow(
        ["# 适用范围-温度°C", rng["temperature_min_c"], rng["temperature_max_c"]]
    )
    w.writerow(["# 外推", interp["extrapolation"]])
    w.writerow([])

    w.writerow(
        [
            "馏分",
            "起点%",
            "终点%",
            "宽度%",
            "起点温度°C",
            "终点温度°C",
            "密度kg/m³",
            "占进料%(曲线基准)",
            "体积%(占回收馏分)",
            "质量%(占回收馏分)",
            "提示",
        ]
    )
    for f in ana["fractions"]:
        w.writerow(
            [
                f["label"],
                f["start_pct"],
                f["end_pct"],
                f["width_pct"],
                _num(f["temp_start_c"]),
                _num(f["temp_end_c"]),
                _num(f["density_kg_m3"]),
                f["pct_of_feed"],
                _num(f["vol_pct_of_recovered"]),
                _num(f["mass_pct_of_recovered"]),
                "；".join(f["warnings"]),
            ]
        )
    w.writerow([])
    w.writerow(["定义总量%", ana["defined_total_pct"]])
    w.writerow(["回收总量%", ana["recovered_pct"]])
    w.writerow(["已分配%", ana["assigned_pct"]])
    w.writerow(["重叠%", ana["overlap_pct"]])
    w.writerow(["残余%", ana["residual_pct"]])
    w.writerow(["损失%", ana["loss_pct"]])
    w.writerow(["总量平衡", "通过" if ana["balance_ok"] else "不平衡，请核实"])
    for warn in ana["warnings"]:
        w.writerow(["# 警告", warn])
    w.writerow(["# 声明", report["disclaimer"]])
    return buf.getvalue()


def _num(v) -> str:
    return "" if v is None else f"{v:.4f}"
