"""质量百分比与体积百分比之间的密度换算。

两个横轴不能混用：体积% 与 质量% 的换算必须基于每段馏分的实测密度。
换算只在"已定义且具备密度的馏分"集合内进行归一，
损失与残余没有密度数据，不参与换算（在结果中单独列示）。
"""
from __future__ import annotations

from typing import Sequence


class DensityError(ValueError):
    """密度数据缺失或非法。"""


def vol_to_mass_pct(widths_vol_pct: Sequence[float], densities_kg_m3: Sequence[float]) -> list[float]:
    """体积% -> 质量%（在传入的馏分集合内归一）。

    mass_i ∝ vol_i × ρ_i；返回各馏分质量占比，合计 100%。
    """
    _check(widths_vol_pct, densities_kg_m3)
    masses = [w * d for w, d in zip(widths_vol_pct, densities_kg_m3)]
    total = sum(masses)
    if total <= 0:
        raise DensityError("馏分总质量为 0，无法换算质量百分比")
    return [m / total * 100.0 for m in masses]


def mass_to_vol_pct(widths_mass_pct: Sequence[float], densities_kg_m3: Sequence[float]) -> list[float]:
    """质量% -> 体积%（在传入的馏分集合内归一）。

    vol_i ∝ mass_i / ρ_i；返回各馏分体积占比，合计 100%。
    """
    _check(widths_mass_pct, densities_kg_m3)
    vols = [w / d for w, d in zip(widths_mass_pct, densities_kg_m3)]
    total = sum(vols)
    if total <= 0:
        raise DensityError("馏分总体积为 0，无法换算体积百分比")
    return [v / total * 100.0 for v in vols]


def mixture_density_kg_m3(widths_vol_pct: Sequence[float], densities_kg_m3: Sequence[float]) -> float:
    """按体积加权的混合密度 = Σ(vol_i × ρ_i) / Σ(vol_i)。"""
    _check(widths_vol_pct, densities_kg_m3)
    vol_total = sum(widths_vol_pct)
    if vol_total <= 0:
        raise DensityError("馏分总体积为 0，无法计算混合密度")
    return sum(w * d for w, d in zip(widths_vol_pct, densities_kg_m3)) / vol_total


def _check(widths: Sequence[float], densities: Sequence[float]) -> None:
    if len(widths) != len(densities):
        raise DensityError("馏分数量与密度数量不一致")
    for d in densities:
        if d is None or d <= 0:
            raise DensityError("密度必须为正数，请补充实测密度数据")
