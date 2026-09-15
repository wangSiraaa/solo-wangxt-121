"""曲线校验测试：下降、回收总量异常、缺端点。"""
from app.services.validation import validate_curve


def codes(issues):
    return {i.code for i in issues}


def test_healthy_curve_has_coverage_infos_only():
    pts = [(0.0, 40.0), (50.0, 200.0), (98.0, 350.0)]
    issues = validate_curve(pts)
    assert not any(i.severity == "error" for i in issues)
    assert not any(i.severity == "warning" for i in issues)
    assert "MISSING_HIGH_ENDPOINT" in codes(issues)  # 终点 98% < 100%


def test_decreasing_curve_warns():
    pts = [(0.0, 40.0), (50.0, 250.0), (60.0, 240.0), (98.0, 350.0)]
    issues = validate_curve(pts)
    dec = [i for i in issues if i.code == "CURVE_DECREASING"]
    assert len(dec) == 1
    assert dec[0].severity == "warning"
    assert "请核实" in dec[0].message


def test_recovery_over_100_warns():
    pts = [(0.0, 40.0), (100.8, 330.0)]
    issues = validate_curve(pts)
    assert "RECOVERY_OVER_100" in codes(issues)


def test_recovery_low_warns():
    pts = [(0.0, 40.0), (85.0, 300.0)]
    issues = validate_curve(pts)
    assert "RECOVERY_LOW" in codes(issues)


def test_missing_low_endpoint_info():
    pts = [(8.0, 168.0), (92.0, 328.5)]
    issues = validate_curve(pts)
    assert "MISSING_LOW_ENDPOINT" in codes(issues)
    assert "MISSING_HIGH_ENDPOINT" in codes(issues)


def test_duplicate_recovery_is_error():
    pts = [(0.0, 40.0), (50.0, 200.0), (50.0, 210.0)]
    issues = validate_curve(pts)
    assert any(i.severity == "error" and i.code == "DUPLICATE_RECOVERY" for i in issues)


def test_too_few_points_is_error():
    issues = validate_curve([(50.0, 200.0)])
    assert any(i.severity == "error" for i in issues)
