"""单位与干湿基换算。

所有内部量采用以下 SI 一致量：
  * 流量体积：L/s；密度：kg/L；脂肪含量：湿基质量分数 (kg fat / kg product)。
换算只依赖线性因子，避免与时间对齐逻辑耦合。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 体积流量 -> L/s
FLOW_TO_LPS = {
    "L/s": 1.0,
    "L/min": 1.0 / 60.0,
    "L/h": 1.0 / 3600.0,
    "m3/h": 1000.0 / 3600.0,
    "m3/s": 1000.0,
}

# 总质量/总脂肪 -> kg（总量类单位）
MASS_TO_KG = {"kg": 1.0, "g": 1e-3, "t": 1000.0}

# 密度 -> kg/L
DENSITY_TO_KG_L = {"kg/L": 1.0, "g/mL": 1.0, "kg/m3": 1e-3}

# 脂肪含量 -> 湿基分数
FAT_FRACTION = {"fraction_wet": 1.0, "percent_wet": 0.01}

# 非脂固形物/总固形物含量 -> 分数
SOLIDS_FRACTION = {"fraction": 1.0, "percent": 0.01}


@dataclass(frozen=True)
class ConvertedValue:
    value: float
    unit_basis: str
    converted: float
    note: str | None = None


def convert_flow(value: float, unit: str) -> float:
    if unit not in FLOW_TO_LPS:
        raise ValueError(f"unsupported flow unit: {unit}")
    return value * FLOW_TO_LPS[unit]


def convert_mass(value: float, unit: str) -> float:
    if unit not in MASS_TO_KG:
        raise ValueError(f"unsupported mass unit: {unit}")
    return value * MASS_TO_KG[unit]


def convert_density(value: float, unit: str) -> float:
    if unit not in DENSITY_TO_KG_L:
        raise ValueError(f"unsupported density unit: {unit}")
    return value * DENSITY_TO_KG_L[unit]


def convert_fat_sample(
    value: float,
    unit: str,
    solids_fraction_wet: float | None = None,
    moisture_pct: float | None = None,
) -> ConvertedValue:
    """把脂肪检测换算为湿基分数。

    支持：
      fraction_wet / percent_wet  直接换算
      fraction_dry / percent_dry  需配合总固形物湿基分数 (solids_fraction_wet)
      g_per_100g_dry              等价 percent_dry
    """
    if unit in FAT_FRACTION:
        return ConvertedValue(value, unit, value * FAT_FRACTION[unit])

    if unit in ("fraction_dry", "percent_dry", "g_per_100g_dry"):
        # 干基 -> 湿基：w_wet = w_dry * TS_wet
        if solids_fraction_wet is None:
            if moisture_pct is not None:
                solids_fraction_wet = 1.0 - moisture_pct / 100.0
            else:
                raise ValueError(
                    "dry-basis fat requires solids fraction (wet basis) or moisture %"
                )
        dry_frac = value if unit == "fraction_dry" else value / 100.0
        wet = dry_frac * solids_fraction_wet
        return ConvertedValue(
            value,
            unit,
            wet,
            note=f"dry->{wet:.4g} wet using TS={solids_fraction_wet:.4f}",
        )

    raise ValueError(f"unsupported fat unit: {unit}")


def relative_uncertainty(abs_u: float | None, rel_u: float | None,
                         measured: float) -> float:
    """统一为相对标准不确定度（1 sigma 约定，见 README）。"""
    if rel_u is not None:
        return max(rel_u, 1e-9)
    if abs_u is not None and abs(measured) > 0:
        return max(abs(abs_u / measured), 1e-9)
    return 0.01  # 未声明时的保守缺省


def combined_relative_uc(terms: list[float]) -> float:
    """独立量按方和根合成相对不确定度。"""
    return math.sqrt(sum(t * t for t in terms))
