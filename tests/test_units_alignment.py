"""单位/干湿基换算 与 时间对齐、量程切换、缺测处理。"""
import math

import pytest

from app.core.alignment import Point, integrate_window
from app.core.units import (
    combined_relative_uc,
    convert_density,
    convert_fat_sample,
    convert_flow,
)


def test_flow_units():
    assert convert_flow(3600.0, "L/h") == pytest.approx(1.0)
    assert convert_flow(60.0, "L/min") == pytest.approx(1.0)
    assert convert_flow(3.6, "m3/h") == pytest.approx(1.0)


def test_density_units():
    assert convert_density(1030, "kg/m3") == pytest.approx(1.03)
    assert convert_density(1.03, "g/mL") == pytest.approx(1.03)


def test_fat_wet_and_dry_basis():
    wet = convert_fat_sample(4.0, "percent_wet")
    assert wet.converted == pytest.approx(0.04)
    dry = convert_fat_sample(10.0, "percent_dry", solids_fraction_wet=0.12)
    assert dry.converted == pytest.approx(0.012)
    dry2 = convert_fat_sample(0.40, "fraction_dry", solids_fraction_wet=0.10)
    assert dry2.converted == pytest.approx(0.04)
    with pytest.raises(ValueError):
        convert_fat_sample(10, "percent_dry")  # 缺总固形物不得换算


def test_uncertainty_rss():
    assert combined_relative_uc([0.03, 0.04]) == pytest.approx(0.05)


def test_integration_constant_rates():
    # q=1 L/s, rho=1 kg/L -> 3600 kg over 1 h
    flow = [Point(0, 1, rel_uc=0.0), Point(3600, 1, rel_uc=0.0)]
    dens = [Point(0, 1.0), Point(3600, 1.0)]
    tot = integrate_window(0, 3600, flow, dens, None, max_gap_s=4000)
    assert tot.present
    assert tot.total == pytest.approx(3600.0)


def test_missing_detection_gap_too_large():
    flow = [Point(0, 1), Point(100, 1)]
    dens = [Point(0, 1), Point(3600, 1)]
    tot = integrate_window(0, 3600, flow, dens, None, max_gap_s=500)
    assert not tot.present
    assert any("flow" in r for r in tot.reasons)


def test_missing_no_samples_at_all():
    dens = [Point(0, 1), Point(3600, 1)]
    tot = integrate_window(0, 3600, [], dens, None, max_gap_s=4000)
    assert not tot.present
    assert "no samples in window" in tot.reasons[0]


def test_range_switch_prefers_lower_uncertainty():
    # 同时刻两量程重叠：高量程 2% vs 低量程 0.5%，应取低量程
    pts = [Point(100, 10.0, rel_uc=0.02, range_id=1),
           Point(100, 10.0, rel_uc=0.005, range_id=2)]
    from app.core.alignment import merge_overlapping_ranges
    merged = merge_overlapping_ranges(pts)
    assert len(merged) == 1
    assert merged[0].range_id == 2


def test_range_switch_gap_creates_missing():
    # 高量程只覆盖前 1/4，低量程只覆盖后 1/4，中间空档
    flow = [Point(0, 1, range_id=1), Point(900, 1, range_id=1),
            Point(2700, 1, range_id=2), Point(3600, 1, range_id=2)]
    dens = [Point(0, 1), Point(3600, 1)]
    tot = integrate_window(0, 3600, flow, dens, None, max_gap_s=900)
    assert not tot.present
