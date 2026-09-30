"""Explicit unit conversions used by the seed and API.

The platform stores calculations in SI mass units (kg, kg/time-window).
Convenience units are converted at the measurement boundary so the solver sees
one coherent unit system.
"""
from app.core.enums import Basis, MetricKind, UncertaintyType

FACTORS = {
    "kg": 1.0,
    "t": 1000.0,
    "tonne": 1000.0,
    "g": 0.001,
    "m3": 1.0,
    "L": 0.001,
    "liter": 0.001,
    "m3/h": 1.0,
    "L/h": 0.001,
    "L/min": 0.06,
    "kg/h": 1.0,
    "kg/s": 3600.0,
    "t/h": 1000.0,
    "kg/m3": 1.0,
    "g/cm3": 1000.0,
    "g/L": 1.0,
    "fraction": 1.0,
    "%": 0.01,
    "g/100g": 0.01,
    "ppm": 1e-6,
    "mg/kg": 1e-6,
}


def factor(unit: str) -> float:
    key = unit.strip()
    if key not in FACTORS:
        raise ValueError(f"unsupported unit {unit!r}; supported units: {sorted(FACTORS)}")
    return FACTORS[key]


def convert_value(value: float, unit: str) -> float:
    return value * factor(unit)


def convert_uncertainty(value: float, u: float, unit: str, kind: UncertaintyType) -> float:
    """Return one-standard-deviation uncertainty in SI units."""
    f = factor(unit)
    if kind == UncertaintyType.RELATIVE:
        return abs(value * u) * f
    sigma = u if kind != UncertaintyType.EXPANDED_95 else u / 1.96
    return sigma * f


def uncertainty_sigma(value: float, u: float, unit: str, uncertainty_type: str) -> float:
    return convert_uncertainty(value, u, unit, UncertaintyType(uncertainty_type))


def dry_to_wet_fraction(x_dry: float, solids_fraction_wet: float) -> float:
    if not 0 <= x_dry <= 1:
        raise ValueError("dry-basis fraction must be between 0 and 1")
    if not 0 < solids_fraction_wet <= 1:
        raise ValueError("solids fraction (wet basis) must be > 0 and <= 1")
    return x_dry * solids_fraction_wet
