"""把 ORM 对象装配成领域服务的辅助函数。"""
from __future__ import annotations

from .. import models
from .fractions import AnalysisResult, DensitySpec, FractionInput, analyze_fractions
from .interpolation import METHOD_DESCRIPTION, METHOD_ID, METHOD_NAME, MonotoneCurve
from .validation import CurveIssue, validate_curve


def sorted_points(exp: models.Experiment) -> list[tuple[float, float]]:
    pts = [(p.recovery_pct, p.temperature_c) for p in exp.points]
    pts.sort(key=lambda p: p[0])
    return pts


def build_curve(exp: models.Experiment) -> MonotoneCurve:
    pts = sorted_points(exp)
    return MonotoneCurve([p[0] for p in pts], [p[1] for p in pts])


def curve_issues(exp: models.Experiment) -> list[CurveIssue]:
    return validate_curve(sorted_points(exp))


def interpolation_meta(curve: MonotoneCurve) -> dict:
    return {
        "method_id": METHOD_ID,
        "method": METHOD_NAME,
        "description": METHOD_DESCRIPTION,
        "extrapolation": "禁止外推：超出数据范围的查询一律拒绝",
        "applicable_range": curve.applicable_range.as_dict(),
        "invertible": curve.invertible,
    }


def density_specs(exp: models.Experiment) -> list[DensitySpec]:
    return [
        DensitySpec(d.label, d.start_pct, d.end_pct, d.density_kg_m3)
        for d in exp.densities
    ]


def run_analysis(
    exp: models.Experiment, fractions: list[FractionInput]
) -> AnalysisResult:
    pts = sorted_points(exp)
    recovered = pts[-1][0]
    curve = build_curve(exp)
    return analyze_fractions(
        fractions,
        recovered_pct=recovered,
        defined_total_pct=exp.defined_total_pct,
        curve_basis=exp.curve_basis,
        curve=curve,
        densities=density_specs(exp),
    )
