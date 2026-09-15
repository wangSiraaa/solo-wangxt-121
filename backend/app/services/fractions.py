"""馏分切割分析：重叠、缺口、残余量、损失与总量平衡。

约定：
- 横轴为"占进料的回收率%"，定义总量 defined_total 默认为 100%；
- 曲线终点回收率 = 实际回收总量 recovered；损失 loss = defined_total - recovered；
- 馏分区间之并集 = 已分配量 assigned；[0, recovered] 内未被覆盖的部分 = 残余 residual；
- 恒等式：assigned + residual + loss = defined_total（balance_ok 据此校验）；
- 馏分区间重叠部分会被重复计数，单独列示并从 assigned 中扣除。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .interpolation import MonotoneCurve, OutOfRangeError
from .units import mass_to_vol_pct, mixture_density_kg_m3, vol_to_mass_pct

BALANCE_TOL = 1e-6


@dataclass(frozen=True)
class FractionInput:
    label: str
    start_pct: float
    end_pct: float


@dataclass(frozen=True)
class DensitySpec:
    """某段馏分的实测密度。"""

    label: str
    start_pct: float
    end_pct: float
    density_kg_m3: float


@dataclass
class FractionResult:
    label: str
    start_pct: float
    end_pct: float
    width_pct: float
    pct_of_feed: float  # 曲线基准下占进料的百分比（= 区间宽度）
    temp_start_c: float | None
    temp_end_c: float | None
    density_kg_m3: float | None
    vol_pct_of_recovered: float | None  # 占已定义馏分回收量的体积%
    mass_pct_of_recovered: float | None  # 占已定义馏分回收量的质量%
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "start_pct": self.start_pct,
            "end_pct": self.end_pct,
            "width_pct": self.width_pct,
            "pct_of_feed": self.pct_of_feed,
            "temp_start_c": self.temp_start_c,
            "temp_end_c": self.temp_end_c,
            "density_kg_m3": self.density_kg_m3,
            "vol_pct_of_recovered": self.vol_pct_of_recovered,
            "mass_pct_of_recovered": self.mass_pct_of_recovered,
            "warnings": self.warnings,
        }


@dataclass
class AnalysisResult:
    curve_basis: str  # "volume" | "mass"，曲线横轴的基准
    defined_total_pct: float
    recovered_pct: float
    assigned_pct: float  # 馏分区间并集覆盖率（扣除重叠）
    overlap_pct: float  # 被重复计数的重叠量
    residual_pct: float  # [0, recovered] 内未覆盖的残余量
    loss_pct: float  # defined_total - recovered
    balance_ok: bool
    fractions: list[FractionResult]
    overlaps: list[dict]  # 两两重叠明细
    gaps: list[dict]  # 缺口区间明细
    warnings: list[str]

    def as_dict(self) -> dict:
        return {
            "curve_basis": self.curve_basis,
            "defined_total_pct": self.defined_total_pct,
            "recovered_pct": self.recovered_pct,
            "assigned_pct": self.assigned_pct,
            "overlap_pct": self.overlap_pct,
            "residual_pct": self.residual_pct,
            "loss_pct": self.loss_pct,
            "balance_ok": self.balance_ok,
            "fractions": [f.as_dict() for f in self.fractions],
            "overlaps": self.overlaps,
            "gaps": self.gaps,
            "warnings": self.warnings,
        }


def _merge_union(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """合并区间，返回不相交的并集。"""
    merged: list[list[float]] = []
    for lo, hi in sorted(intervals):
        if merged and lo <= merged[-1][1] + BALANCE_TOL:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def _match_density(frac: FractionInput, densities: list[DensitySpec]) -> DensitySpec | None:
    """先按标签精确匹配，再按区间重叠最大者匹配。"""
    for d in densities:
        if d.label == frac.label:
            return d
    best: DensitySpec | None = None
    best_overlap = 0.0
    for d in densities:
        ov = min(frac.end_pct, d.end_pct) - max(frac.start_pct, d.start_pct)
        if ov > best_overlap:
            best, best_overlap = d, ov
    return best


def analyze_fractions(
    fractions: list[FractionInput],
    *,
    recovered_pct: float,
    defined_total_pct: float = 100.0,
    curve_basis: str = "volume",
    curve: MonotoneCurve | None = None,
    densities: list[DensitySpec] | None = None,
) -> AnalysisResult:
    """对一组馏分切点做完整分析。"""
    if curve_basis not in ("volume", "mass"):
        raise ValueError("curve_basis 必须是 'volume' 或 'mass'")
    densities = densities or []
    warnings: list[str] = []
    results: list[FractionResult] = []

    loss_pct = defined_total_pct - recovered_pct
    if loss_pct < -BALANCE_TOL:
        warnings.append(
            f"回收总量 {recovered_pct}% 超过定义总量 {defined_total_pct}%，计量异常，请核实"
        )

    valid_intervals: list[tuple[float, float]] = []  # 裁剪到 [0, recovered] 的有效区间
    for f in fractions:
        fw: list[str] = []
        if f.end_pct < f.start_pct - BALANCE_TOL:
            fw.append(
                f"馏分「{f.label}」终点 {f.end_pct}% 小于起点 {f.start_pct}%，区间无效，未计入覆盖"
            )
            results.append(
                FractionResult(f.label, f.start_pct, f.end_pct, 0.0, 0.0, None, None, None, None, None, fw)
            )
            continue
        width = max(0.0, f.end_pct - f.start_pct)
        if width <= BALANCE_TOL:
            fw.append(f"馏分「{f.label}」相邻切点相等（{f.start_pct}%），宽度为 0，产率为 0")
        if f.start_pct < -BALANCE_TOL or f.end_pct > recovered_pct + BALANCE_TOL:
            fw.append(
                f"馏分「{f.label}」[{f.start_pct}%, {f.end_pct}%] 超出回收范围 "
                f"[0%, {recovered_pct}%]，超出部分不计入（不外推）"
            )
        # 温度取值（严格不外推）
        t_start = t_end = None
        if curve is not None and width > BALANCE_TOL:
            lo, hi = curve.recovery_range
            try:
                t_start = curve.temperature_at(f.start_pct)
            except OutOfRangeError:
                fw.append(
                    f"馏分「{f.label}」起点 {f.start_pct}% 超出曲线数据范围 [{lo}%, {hi}%]，"
                    f"无法给出对应温度（不外推）"
                )
            try:
                t_end = curve.temperature_at(f.end_pct)
            except OutOfRangeError:
                fw.append(
                    f"馏分「{f.label}」终点 {f.end_pct}% 超出曲线数据范围 [{lo}%, {hi}%]，"
                    f"无法给出对应温度（不外推）"
                )
        clipped_lo = max(0.0, min(f.start_pct, recovered_pct))
        clipped_hi = max(0.0, min(f.end_pct, recovered_pct))
        if clipped_hi > clipped_lo + BALANCE_TOL:
            valid_intervals.append((clipped_lo, clipped_hi))
        results.append(
            FractionResult(
                label=f.label,
                start_pct=f.start_pct,
                end_pct=f.end_pct,
                width_pct=width,
                pct_of_feed=width,
                temp_start_c=t_start,
                temp_end_c=t_end,
                density_kg_m3=None,
                vol_pct_of_recovered=None,
                mass_pct_of_recovered=None,
                warnings=fw,
            )
        )

    # ---- 覆盖、重叠、缺口、残余 ----------------------------------------
    union = _merge_union(valid_intervals)
    assigned_pct = sum(hi - lo for lo, hi in union)
    overlap_pct = sum(hi - lo for lo, hi in valid_intervals) - assigned_pct

    overlaps: list[dict] = []
    valid_fracs = [f for f in fractions if f.end_pct > f.start_pct + BALANCE_TOL]
    for i in range(len(valid_fracs)):
        for j in range(i + 1, len(valid_fracs)):
            a, b = valid_fracs[i], valid_fracs[j]
            ov = min(a.end_pct, b.end_pct) - max(a.start_pct, b.start_pct)
            if ov > BALANCE_TOL:
                overlaps.append(
                    {
                        "fraction_a": a.label,
                        "fraction_b": b.label,
                        "start_pct": max(a.start_pct, b.start_pct),
                        "end_pct": min(a.end_pct, b.end_pct),
                        "overlap_pct": ov,
                    }
                )
    if overlaps:
        warnings.append(
            "馏分区间存在重叠，重叠部分被重复计数，请调整切点：" + "；".join(
                f"「{o['fraction_a']}」与「{o['fraction_b']}」重叠 {round(o['overlap_pct'], 4)}%"
                for o in overlaps
            )
        )

    gaps: list[dict] = []
    cursor = 0.0
    for lo, hi in union:
        if lo > cursor + BALANCE_TOL:
            gaps.append({"start_pct": cursor, "end_pct": lo, "width_pct": lo - cursor})
        cursor = max(cursor, hi)
    if recovered_pct > cursor + BALANCE_TOL:
        gaps.append({"start_pct": cursor, "end_pct": recovered_pct, "width_pct": recovered_pct - cursor})
    residual_pct = sum(g["width_pct"] for g in gaps)

    balance_ok = abs(assigned_pct + residual_pct + loss_pct - defined_total_pct) <= max(
        BALANCE_TOL, 1e-9 * abs(defined_total_pct)
    )

    # ---- 密度匹配与质量/体积换算 ---------------------------------------
    convertible_idx: list[int] = []
    for idx, (f, res) in enumerate(zip(fractions, results)):
        if res.width_pct <= BALANCE_TOL:
            continue
        spec = _match_density(f, densities)
        if spec is None:
            res.warnings.append(
                f"馏分「{f.label}」缺少实测密度，无法换算质量/体积百分比"
            )
        else:
            res.density_kg_m3 = spec.density_kg_m3
            convertible_idx.append(idx)

    if convertible_idx:
        widths = [results[i].width_pct for i in convertible_idx]
        dens = [results[i].density_kg_m3 for i in convertible_idx]
        if curve_basis == "volume":
            vol_pcts = [w / sum(widths) * 100.0 for w in widths]
            mass_pcts = vol_to_mass_pct(widths, dens)
        else:
            mass_pcts = [w / sum(widths) * 100.0 for w in widths]
            vol_pcts = mass_to_vol_pct(widths, dens)
        for k, i in enumerate(convertible_idx):
            results[i].vol_pct_of_recovered = vol_pcts[k]
            results[i].mass_pct_of_recovered = mass_pcts[k]
        if len(convertible_idx) < len([r for r in results if r.width_pct > BALANCE_TOL]):
            warnings.append(
                "部分馏分缺少密度，质量/体积百分比仅在具备密度的馏分集合内归一"
            )
        if residual_pct > BALANCE_TOL:
            warnings.append(
                f"残余量 {round(residual_pct, 4)}% 未分配馏分且无密度数据，不参与质量/体积换算"
            )

    return AnalysisResult(
        curve_basis=curve_basis,
        defined_total_pct=defined_total_pct,
        recovered_pct=recovered_pct,
        assigned_pct=assigned_pct,
        overlap_pct=overlap_pct,
        residual_pct=residual_pct,
        loss_pct=loss_pct,
        balance_ok=balance_ok,
        fractions=results,
        overlaps=overlaps,
        gaps=gaps,
        warnings=warnings,
    )
