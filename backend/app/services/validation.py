"""曲线数据校验：发现可疑数据时先提示核实，而不是静默接受。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# 回收总量低于该值时提示可能存在未计量损失
LOW_RECOVERY_THRESHOLD_PCT = 90.0
# 起点高于该值时提示缺少低回收端点
LOW_ENDPOINT_GAP_PCT = 5.0


@dataclass(frozen=True)
class CurveIssue:
    severity: str  # "error" | "warning" | "info"
    code: str
    message: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "message": self.message}


def validate_curve(points: Sequence[tuple[float, float]]) -> list[CurveIssue]:
    """校验累积蒸馏曲线。

    points: 按回收率排序后的 (回收率%, 温度°C) 序列。
    返回问题列表；存在 error 级问题时不应继续插值。
    """
    issues: list[CurveIssue] = []
    n = len(points)
    if n < 2:
        issues.append(
            CurveIssue("error", "TOO_FEW_POINTS", "至少需要两个数据点才能建立插值曲线")
        )
        return issues

    recoveries = [p[0] for p in points]
    temps = [p[1] for p in points]

    for i in range(1, n):
        if recoveries[i] <= recoveries[i - 1]:
            issues.append(
                CurveIssue(
                    "error",
                    "DUPLICATE_RECOVERY",
                    f"回收率 {recoveries[i]}% 出现重复或倒序，无法建立单调插值，请核实数据",
                )
            )
    if any(i.severity == "error" for i in issues):
        return issues

    # 曲线下降：温度随回收率降低 —— 蒸馏曲线不应出现，提示核实
    for i in range(1, n):
        if temps[i] < temps[i - 1]:
            issues.append(
                CurveIssue(
                    "warning",
                    "CURVE_DECREASING",
                    f"回收率 {recoveries[i - 1]}%→{recoveries[i]}% 处温度由 "
                    f"{temps[i - 1]}°C 降至 {temps[i]}°C，曲线下降，请核实该段数据",
                )
            )

    # 回收总量异常
    total = recoveries[-1]
    if total > 100.0:
        issues.append(
            CurveIssue(
                "warning",
                "RECOVERY_OVER_100",
                f"回收总量 {total}% 超过 100%，计量异常，请核实试验数据",
            )
        )
    elif total < LOW_RECOVERY_THRESHOLD_PCT:
        issues.append(
            CurveIssue(
                "warning",
                "RECOVERY_LOW",
                f"回收总量仅 {total}%，可能存在未计量损失，请核实试验数据",
            )
        )

    # 端点覆盖情况（缺端点会影响可切范围，但不阻止使用）
    if recoveries[0] > LOW_ENDPOINT_GAP_PCT:
        issues.append(
            CurveIssue(
                "info",
                "MISSING_LOW_ENDPOINT",
                f"曲线起点为回收率 {recoveries[0]}%，缺少低回收端点；"
                f"低于 {recoveries[0]}% 的切点无法取值（不外推）",
            )
        )
    if total < 100.0:
        issues.append(
            CurveIssue(
                "info",
                "MISSING_HIGH_ENDPOINT",
                f"曲线终点为回收率 {total}%，高于该值的切点无法取值（不外推）；"
                f"未回收部分按损失/残余处理",
            )
        )
    return issues
