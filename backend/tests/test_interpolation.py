"""单调插值测试：PCHIP 保点、单调、不外推。"""
import numpy as np
import pytest

from app.services.interpolation import (
    MonotoneCurve,
    NonMonotonicError,
    OutOfRangeError,
)

# 算例1：缺端点曲线（8% 起点，92% 终点）
RECOVERY = [8, 10, 20, 30, 40, 50, 60, 70, 80, 90, 92]
TEMP = [168.0, 172.5, 191.0, 208.0, 224.5, 241.0, 258.5, 277.0, 298.0, 322.0, 328.5]


@pytest.fixture()
def curve():
    return MonotoneCurve(RECOVERY, TEMP)


def test_passes_through_data_points(curve):
    for r, t in zip(RECOVERY, TEMP):
        assert curve.temperature_at(r) == pytest.approx(t, abs=1e-9)


def test_monotone_between_points(curve):
    grid = np.linspace(8, 92, 500)
    temps = [curve.temperature_at(g) for g in grid]
    assert all(b >= a - 1e-9 for a, b in zip(temps, temps[1:]))


def test_no_extrapolation_low(curve):
    """缺低回收端点：低于 8% 的查询必须拒绝。"""
    with pytest.raises(OutOfRangeError, match="不外推"):
        curve.temperature_at(5.0)


def test_no_extrapolation_high(curve):
    """缺高回收端点：高于 92% 的查询必须拒绝，不虚构高温数据。"""
    with pytest.raises(OutOfRangeError, match="不外推"):
        curve.temperature_at(95.0)


def test_boundary_points_allowed(curve):
    assert curve.temperature_at(8.0) == pytest.approx(168.0)
    assert curve.temperature_at(92.0) == pytest.approx(328.5)


def test_inverse_lookup(curve):
    assert curve.recovery_at(241.0) == pytest.approx(50.0, abs=1e-9)
    assert curve.recovery_at(200.0) == pytest.approx(curve.recovery_at(200.0))


def test_inverse_out_of_range(curve):
    with pytest.raises(OutOfRangeError):
        curve.recovery_at(400.0)  # 高于最高温度，不外推


def test_duplicate_recovery_rejected():
    with pytest.raises(NonMonotonicError):
        MonotoneCurve([10, 20, 20, 30], [100, 150, 155, 200])


def test_flat_temperature_not_invertible():
    curve = MonotoneCurve([10, 20, 30], [100.0, 100.0, 150.0])
    assert not curve.invertible
    with pytest.raises(NonMonotonicError):
        curve.recovery_at(120.0)


def test_applicable_range(curve):
    rng = curve.applicable_range.as_dict()
    assert rng["recovery_min_pct"] == 8.0
    assert rng["recovery_max_pct"] == 92.0
    assert rng["temperature_min_c"] == 168.0
    assert rng["temperature_max_c"] == 328.5


def test_too_few_points():
    with pytest.raises(ValueError):
        MonotoneCurve([50], [200])
