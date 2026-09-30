from datetime import datetime, timedelta, timezone
import math

from app.services.aggregation import aggregate_edges
from app.services.units import dry_to_wet_fraction

T0 = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=30)
T2 = T0 + timedelta(hours=1)


class R:
    def __init__(self, id, metric, value, unit, start, end=None, sigma=.01,
                 uncertainty_type="stddev", basis="wet", range_code=None):
        self.target_type="edge"; self.target_id=1; self.id=id; self.metric=metric; self.value=value; self.unit=unit
        self.period_start=start; self.period_end=end; self.uncertainty_value=sigma
        self.uncertainty_type=uncertainty_type; self.basis=basis; self.range_code=range_code


def test_range_switch_mass_flow_is_piecewise_integrated():
    rows = [
        R(1, "mass_flow", 60, "kg/h", T0, T1, .01, range_code="low"),
        R(2, "mass_flow", 40, "kg/h", T1, T2, .01, range_code="high"),
        R(3, "fat_fraction", .4, "fraction", T0, None, .0001),
    ]
    agg = aggregate_edges([1], rows, T0, T2, {1: "e"})[1]
    assert agg.measured_mass
    assert math.isclose(agg.mass, 50.0, rel_tol=1e-12)
    assert math.isclose(agg.fat_mass, 20.0, rel_tol=1e-12)
    assert "range_switch" in agg.flags


def test_volume_density_different_granularity_and_units():
    rows = [
        R(1, "volume_flow", 1000, "L/h", T0, T2, 1),
        R(2, "density", 1.030, "g/cm3", T0, None, .001),
        R(3, "fat_fraction", 4, "%", T0, None, .01),
    ]
    agg = aggregate_edges([1], rows, T0, T2, {1: "e"})[1]
    assert math.isclose(agg.mass, 1030.0, rel_tol=1e-12)
    assert math.isclose(agg.fat_mass, 41.2, rel_tol=1e-12)


def test_expanded_relative_and_dry_basis_conversion():
    rows = [
        R(1, "mass_flow", 1000, "kg/h", T0, T2, .01, "relative"),
        R(2, "fat_fraction", .5, "fraction", T0, None, .02, "expanded_95", "dry"),
        R(3, "solids_fraction", .10, "fraction", T0, None, .001),
    ]
    agg = aggregate_edges([1], rows, T0, T2, {1: "e"})[1]
    assert math.isclose(agg.fat_mass, 50.0, rel_tol=1e-12)
    assert math.isclose(dry_to_wet_fraction(.5, .1), .05)


def test_dry_fat_without_solids_does_not_invent_fat():
    rows = [
        R(1, "mass_flow", 1000, "kg/h", T0, T2),
        R(2, "fat_fraction", .5, "fraction", T0, None, basis="dry"),
    ]
    agg = aggregate_edges([1], rows, T0, T2, {1: "e"})[1]
    assert agg.fat_mass is None
    assert "dry_fat_without_coincident_solids" in agg.flags
