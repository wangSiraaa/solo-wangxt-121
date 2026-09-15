"""单调插值服务。

使用 SciPy 的 PCHIP（分段三次 Hermite 单调插值）对累积蒸馏曲线做插值。
核心约束：
- 只在数据覆盖范围内插值，**不做任何外推**；
- 回收率轴必须严格递增；
- 温度 -> 回收率 的反查只有在温度严格单调递增时才可用。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator

METHOD_ID = "pchip"
METHOD_NAME = "PCHIP 单调三次 Hermite 插值"
METHOD_DESCRIPTION = (
    "scipy.interpolate.PchipInterpolator：分段三次 Hermite 多项式，"
    "保证插值结果在相邻数据点之间单调，不会引入过冲。"
    "仅在试验数据覆盖范围内有效，超出范围一律拒绝（不外推）。"
)


class OutOfRangeError(ValueError):
    """查询点超出数据覆盖范围（不允许外推）。"""


class NonMonotonicError(ValueError):
    """曲线不满足单调性要求，无法建立插值。"""


@dataclass(frozen=True)
class ApplicableRange:
    """插值适用范围。"""

    recovery_min_pct: float
    recovery_max_pct: float
    temperature_min_c: float
    temperature_max_c: float

    def as_dict(self) -> dict:
        return {
            "recovery_min_pct": self.recovery_min_pct,
            "recovery_max_pct": self.recovery_max_pct,
            "temperature_min_c": self.temperature_min_c,
            "temperature_max_c": self.temperature_max_c,
        }


class MonotoneCurve:
    """一条累积蒸馏曲线：x = 回收率(%)，y = 温度(°C)。"""

    def __init__(self, recovery_pct, temperature_c):
        x = np.asarray(recovery_pct, dtype=float)
        y = np.asarray(temperature_c, dtype=float)
        if x.size != y.size:
            raise ValueError("回收率与温度数据点数量不一致")
        if x.size < 2:
            raise ValueError("至少需要两个数据点才能建立插值曲线")
        order = np.argsort(x, kind="stable")
        self._x = x[order]
        self._y = y[order]
        if np.any(np.diff(self._x) <= 0):
            raise NonMonotonicError("回收率存在重复值，无法建立单调插值，请核实数据")
        self._t_of_r = PchipInterpolator(self._x, self._y, extrapolate=False)
        # 反查（温度 -> 回收率）只在温度严格递增时才有定义
        self._r_of_t: PchipInterpolator | None = None
        if bool(np.all(np.diff(self._y) > 0)):
            self._r_of_t = PchipInterpolator(self._y, self._x, extrapolate=False)

    # ---- 元信息 ---------------------------------------------------------
    @property
    def recovery_range(self) -> tuple[float, float]:
        return float(self._x[0]), float(self._x[-1])

    @property
    def temperature_range(self) -> tuple[float, float]:
        return float(self._y.min()), float(self._y.max())

    @property
    def invertible(self) -> bool:
        return self._r_of_t is not None

    @property
    def applicable_range(self) -> ApplicableRange:
        r_lo, r_hi = self.recovery_range
        t_lo, t_hi = self.temperature_range
        return ApplicableRange(r_lo, r_hi, t_lo, t_hi)

    # ---- 插值 -----------------------------------------------------------
    def temperature_at(self, recovery_pct: float) -> float:
        """给定回收率(%)，返回温度(°C)。超出范围抛 OutOfRangeError。"""
        lo, hi = self.recovery_range
        v = float(recovery_pct)
        if not (lo <= v <= hi):
            raise OutOfRangeError(
                f"回收率 {v}% 超出数据范围 [{lo}%, {hi}%]，不外推，请补充试验数据"
            )
        return float(self._t_of_r(v))

    def recovery_at(self, temperature_c: float) -> float:
        """给定温度(°C)，返回回收率(%)。温度非单调或超范围时抛错。"""
        if self._r_of_t is None:
            raise NonMonotonicError(
                "温度未随回收率严格单调上升，无法反查回收率，请核实曲线数据"
            )
        lo, hi = float(self._y[0]), float(self._y[-1])
        v = float(temperature_c)
        if not (lo <= v <= hi):
            raise OutOfRangeError(
                f"温度 {v}°C 超出数据范围 [{lo}°C, {hi}°C]，不外推，请补充试验数据"
            )
        return float(self._r_of_t(v))
