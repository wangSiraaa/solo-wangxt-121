"""馏分切割分析测试：重叠、缺口、残余、损失、总量平衡、密度换算。"""
import pytest

from app.services.fractions import DensitySpec, FractionInput, analyze_fractions
from app.services.interpolation import MonotoneCurve

# 算例2 曲线：0% → 96.5%
RECOVERY = [0, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 96.5]
TEMP = [38.0, 62.0, 84.0, 128.0, 172.0, 214.0, 252.0, 288.0, 322.0, 355.0, 388.0, 412.0]
DENSITIES = [
    DensitySpec("石脑油", 0, 20, 720.0),
    DensitySpec("煤油", 20, 40, 798.0),
    DensitySpec("柴油", 40, 70, 845.0),
    DensitySpec("重油", 70, 96.5, 912.0),
]


def analyze(fractions, **kw):
    kw.setdefault("recovered_pct", 96.5)
    kw.setdefault("curve", MonotoneCurve(RECOVERY, TEMP))
    kw.setdefault("densities", DENSITIES)
    return analyze_fractions(fractions, **kw)


# ---- 相邻切点相等 -------------------------------------------------------
def test_adjacent_equal_cut_points_no_gap_no_overlap():
    """首尾相接的切点：无重叠、无缺口，残余为 0。"""
    res = analyze([
        FractionInput("石脑油", 0, 20),
        FractionInput("煤油", 20, 40),
        FractionInput("柴油", 40, 70),
        FractionInput("重油", 70, 96.5),
    ])
    assert res.overlap_pct == pytest.approx(0.0)
    assert res.overlaps == []
    assert res.gaps == []
    assert res.residual_pct == pytest.approx(0.0)
    assert res.assigned_pct == pytest.approx(96.5)
    assert res.loss_pct == pytest.approx(3.5)
    assert res.balance_ok


def test_zero_width_fraction_flagged_but_balance_holds():
    """零宽度馏分（相邻切点完全相等）：产率为 0 并提示，总量仍平衡。"""
    res = analyze([
        FractionInput("石脑油", 0, 20),
        FractionInput("零宽演示", 20, 20),
        FractionInput("煤油", 20, 40),
        FractionInput("柴油", 40, 70),
        FractionInput("重油", 70, 96.5),
    ])
    zero = res.fractions[1]
    assert zero.width_pct == 0.0
    assert zero.pct_of_feed == 0.0
    assert any("宽度为 0" in w for w in zero.warnings)
    assert res.assigned_pct == pytest.approx(96.5)
    assert res.balance_ok


# ---- 重叠与缺口 ---------------------------------------------------------
def test_overlap_detected_and_deducted():
    res = analyze([
        FractionInput("A", 0, 30),
        FractionInput("B", 20, 50),
        FractionInput("C", 50, 96.5),
    ])
    assert res.overlap_pct == pytest.approx(10.0)
    assert len(res.overlaps) == 1
    assert res.overlaps[0]["fraction_a"] == "A"
    assert res.overlaps[0]["overlap_pct"] == pytest.approx(10.0)
    # 并集覆盖率不重复计数
    assert res.assigned_pct == pytest.approx(96.5)
    assert res.balance_ok
    assert any("重叠" in w for w in res.warnings)


def test_gaps_become_residual():
    res = analyze([
        FractionInput("A", 0, 20),
        FractionInput("B", 40, 70),
    ])
    widths = {(g["start_pct"], g["end_pct"]): g["width_pct"] for g in res.gaps}
    assert widths[(20.0, 40.0)] == pytest.approx(20.0)
    assert widths[(70.0, 96.5)] == pytest.approx(26.5)
    assert res.residual_pct == pytest.approx(46.5)
    assert res.assigned_pct == pytest.approx(50.0)
    # 已分配 + 残余 + 损失 = 定义总量
    assert res.assigned_pct + res.residual_pct + res.loss_pct == pytest.approx(100.0)
    assert res.balance_ok


def test_loss_from_incomplete_recovery():
    res = analyze([FractionInput("全部", 0, 96.5)])
    assert res.loss_pct == pytest.approx(3.5)
    assert res.balance_ok


def test_recovery_over_defined_total_warns():
    res = analyze_fractions(
        [FractionInput("A", 0, 50)],
        recovered_pct=100.8,
        defined_total_pct=100.0,
    )
    assert res.loss_pct == pytest.approx(-0.8)
    assert any("超过定义总量" in w for w in res.warnings)


# ---- 密度换算 -----------------------------------------------------------
def test_mass_pct_differs_from_vol_pct():
    res = analyze([
        FractionInput("石脑油", 0, 20),
        FractionInput("煤油", 20, 40),
        FractionInput("柴油", 40, 70),
        FractionInput("重油", 70, 96.5),
    ])
    fr = res.fractions
    # 体积%（占回收馏分）
    assert fr[0].vol_pct_of_recovered == pytest.approx(20 / 96.5 * 100)
    # 质量% 通过密度换算，与体积% 不同
    assert fr[0].mass_pct_of_recovered == pytest.approx(14400 / 79878 * 100)
    assert fr[0].mass_pct_of_recovered != pytest.approx(fr[0].vol_pct_of_recovered)
    assert sum(f.mass_pct_of_recovered for f in fr) == pytest.approx(100.0)
    # 占进料的产率（曲线基准）
    assert fr[2].pct_of_feed == pytest.approx(30.0)


def test_missing_density_warns():
    res = analyze_fractions(
        [FractionInput("未知段", 0, 20), FractionInput("石脑油", 20, 40)],
        recovered_pct=96.5,
        densities=[DensitySpec("石脑油", 20, 40, 798.0)],
    )
    assert res.fractions[0].density_kg_m3 is None
    assert res.fractions[0].mass_pct_of_recovered is None
    assert any("缺少实测密度" in w for w in res.fractions[0].warnings)
    assert res.fractions[1].mass_pct_of_recovered == pytest.approx(100.0)


def test_mass_basis_curve_converts_to_volume():
    """曲线基准为质量% 时，反算体积%。"""
    res = analyze_fractions(
        [FractionInput("轻", 0, 50), FractionInput("重", 50, 96.5)],
        recovered_pct=96.5,
        curve_basis="mass",
        densities=[DensitySpec("轻", 0, 50, 720.0), DensitySpec("重", 50, 96.5, 912.0)],
    )
    fr = res.fractions
    assert fr[0].mass_pct_of_recovered == pytest.approx(50 / 96.5 * 100)
    # vol ∝ mass/ρ：轻组分密度低，体积占比应高于质量占比
    assert fr[0].vol_pct_of_recovered > fr[0].mass_pct_of_recovered
    assert sum(f.vol_pct_of_recovered for f in fr) == pytest.approx(100.0)


# ---- 温度取值与缺端点 -----------------------------------------------------
def test_fraction_temperatures_from_curve():
    res = analyze([FractionInput("煤油", 20, 40)])
    f = res.fractions[0]
    assert f.temp_start_c == pytest.approx(128.0)
    assert f.temp_end_c == pytest.approx(214.0)


def test_missing_endpoint_blocks_temperature():
    """算例1：曲线从 8% 开始，0% 起点的馏分取不到起点温度，且不外推。"""
    c = MonotoneCurve([8, 10, 50, 92], [168.0, 172.5, 241.0, 328.5])
    res = analyze_fractions(
        [FractionInput("低回收段", 0, 20)],
        recovered_pct=92.0,
        curve=c,
    )
    f = res.fractions[0]
    assert f.temp_start_c is None
    assert f.temp_end_c is not None
    assert any("不外推" in w for w in f.warnings)


def test_fraction_beyond_recovery_clipped_and_warned():
    res = analyze([FractionInput("A", 0, 90), FractionInput("B", 90, 100)])
    assert any("超出回收范围" in w for w in res.fractions[1].warnings)
    assert res.assigned_pct == pytest.approx(96.5)
    assert res.balance_ok


def test_inverted_fraction_invalid():
    res = analyze([FractionInput("倒置", 60, 40)])
    assert res.fractions[0].width_pct == 0.0
    assert any("区间无效" in w for w in res.fractions[0].warnings)
    assert res.balance_ok
