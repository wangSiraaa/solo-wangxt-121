"""密度换算测试：质量% 与 体积% 不可混用。"""
import pytest

from app.services.units import (
    DensityError,
    mass_to_vol_pct,
    mixture_density_kg_m3,
    vol_to_mass_pct,
)

# 算例2：四段馏分，密度随馏分变化
WIDTHS = [20.0, 20.0, 30.0, 26.5]
DENSITIES = [720.0, 798.0, 845.0, 912.0]


def test_vol_to_mass_differs_from_vol():
    mass = vol_to_mass_pct(WIDTHS, DENSITIES)
    vol = [w / sum(WIDTHS) * 100 for w in WIDTHS]
    assert sum(mass) == pytest.approx(100.0)
    # 密度低于平均的石脑油，质量% 应低于体积%；密度高的重油相反
    assert mass[0] < vol[0]
    assert mass[3] > vol[3]
    # 精确值核对
    assert mass[0] == pytest.approx(14400 / 79878 * 100, rel=1e-9)
    assert mass[3] == pytest.approx(24168 / 79878 * 100, rel=1e-9)


def test_mass_to_vol_roundtrip():
    mass = vol_to_mass_pct(WIDTHS, DENSITIES)
    vol_back = mass_to_vol_pct(mass, DENSITIES)
    vol_expected = [w / sum(WIDTHS) * 100 for w in WIDTHS]
    assert vol_back == pytest.approx(vol_expected, rel=1e-9)


def test_equal_density_makes_axes_equal():
    mass = vol_to_mass_pct([10.0, 20.0, 30.0], [850.0, 850.0, 850.0])
    assert mass == pytest.approx([10 / 60 * 100, 20 / 60 * 100, 30 / 60 * 100])


def test_mixture_density():
    rho = mixture_density_kg_m3(WIDTHS, DENSITIES)
    assert rho == pytest.approx(79878 / 96.5, rel=1e-9)


def test_zero_density_rejected():
    with pytest.raises(DensityError):
        vol_to_mass_pct([10.0], [0.0])


def test_length_mismatch_rejected():
    with pytest.raises(DensityError):
        vol_to_mass_pct([10.0, 20.0], [800.0])
