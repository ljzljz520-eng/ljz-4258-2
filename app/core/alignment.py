"""时间对齐与积分。

设计取舍（详见 README「时间对齐」一节）：
  * 流量/密度/脂肪检测粒度不同：统一取所有原始时间戳的并集作为评估网格，
    每个指标各自在相邻样本间做分段线性插值；不做重采样到固定频率，
    避免高频流量被低频栅格平均掉。
  * 段内总质量/总脂肪用时间加权（梯形）积分：
        M = ∫ q(t) ρ(t) dt ;  F = ∫ q(t) ρ(t) w(t) dt
  * 覆盖性检查：指标首末样本必须覆盖段窗（允许 <= gap_tolerance 外推），
    且相邻样本间隔不得超过 max_gap_s，否则判为缺测，交由可辨识性检查，
    绝不用插补值冒充测量。
  * 量程切换：同一时间段存在多台量程重叠时，若都有效，取不确定度更小者；
    出现空档（两台都不覆盖）则视为缺测；样本的 range_id 仅用于审计。
  * 迟到样本不在此处处理——作业冻结后到达的样本由调度层判定为失配，
    旧结果保留可见但不再是当前图。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

_trapz = getattr(np, 'trapezoid', None) or np.trapz


@dataclass
class Point:
    t: float          # Unix 秒
    v: float
    abs_uc: float | None = None
    rel_uc: float | None = None
    range_id: int | None = None
    sample_id: int | None = None


@dataclass
class SeriesCoverage:
    start: float
    end: float
    max_gap_s: float
    extrap_tolerance_s: float = 0.0


@dataclass
class IntegratedTotal:
    total: float
    abs_uc: float
    present: bool
    n_grid: int
    reasons: list[str] = field(default_factory=list)
    source_samples: list[int] = field(default_factory=list)


def _coverage_ok(points: list[Point], cov: SeriesCoverage) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not points:
        return False, ["no samples in window"]
    ts = [p.t for p in points]
    if min(ts) > cov.start + cov.extrap_tolerance_s:
        reasons.append(
            f"first sample {min(ts)} later than window start {cov.start}"
        )
    if max(ts) < cov.end - cov.extrap_tolerance_s:
        reasons.append(
            f"last sample {max(ts)} earlier than window end {cov.end}"
        )
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    if gaps and max(gaps) > cov.max_gap_s:
        reasons.append(f"sample gap {max(gaps):.0f}s exceeds {cov.max_gap_s:.0f}s")
    return (not reasons), reasons


def _interp(times: np.ndarray, pts: list[Point]) -> np.ndarray:
    ts = np.array([p.t for p in pts], dtype=float)
    vs = np.array([p.v for p in pts], dtype=float)
    order = np.argsort(ts)
    # np.interp 对窗口外做钳制（外推距离已在覆盖性检查中受限）
    return np.interp(times, ts[order], vs[order])


def _rel_uc_grid(times: np.ndarray, pts: list[Point], measured: np.ndarray
                 ) -> np.ndarray:
    out = np.full_like(times, 0.01)
    ts = np.array([p.t for p in pts], dtype=float)
    order = np.argsort(ts)
    rel = np.array([
        p.rel_uc if p.rel_uc is not None
        else (abs(p.abs_uc / p.v) if p.abs_uc is not None and p.v != 0 else 0.01)
        for p in pts
    ])
    return np.interp(times, ts[order], rel[order])


def merge_overlapping_ranges(points: list[Point]) -> list[Point]:
    """同一时刻多量程重叠时，保留相对不确定度更小的点。"""
    by_t: dict[float, Point] = {}
    for p in points:
        old = by_t.get(p.t)
        if old is None:
            by_t[p.t] = p
            continue
        u_new = p.rel_uc if p.rel_uc is not None else (
            abs(p.abs_uc / p.v) if p.abs_uc is not None and p.v else 1.0)
        u_old = old.rel_uc if old.rel_uc is not None else (
            abs(old.abs_uc / old.v) if old.abs_uc is not None and old.v else 1.0)
        if u_new < u_old:
            by_t[p.t] = p
    return [by_t[t] for t in sorted(by_t)]


def integrate_window(
    t_start: float,
    t_end: float,
    flow: list[Point],
    density: list[Point],
    fat: list[Point] | None,
    max_gap_s: float,
    extrap_tolerance_s: float = 0.0,
) -> IntegratedTotal:
    """积分段内总质量 (fat=None) 或总脂肪 (fat 给定)。

    返回的不确定度为按积分网格方和根传播的 1σ 绝对值（一阶近似，
    忽略插值函数间协方差，取舍见 README）。
    """
    cov = SeriesCoverage(t_start, t_end, max_gap_s, extrap_tolerance_s)
    reasons: list[str] = []
    src: set[int] = set()
    ok_f, r1 = _coverage_ok(flow, cov)
    ok_d, r2 = _coverage_ok(density, cov)
    reasons += [f"flow: {r}" for r in r1]
    reasons += [f"density: {r}" for r in r2]
    ok = ok_f and ok_d
    if fat is not None:
        ok_w, r3 = _coverage_ok(fat, cov)
        reasons += [f"fat: {r}" for r in r3]
        ok = ok and ok_w

    flow = merge_overlapping_ranges(flow)
    density = merge_overlapping_ranges(density)
    if fat is not None:
        fat = merge_overlapping_ranges(fat)

    for lst in (flow, density, fat or []):
        for p in lst:
            if p.sample_id is not None:
                src.add(p.sample_id)

    if not ok:
        return IntegratedTotal(0.0, math.inf, False, 0, reasons, sorted(src))

    all_ts = [p.t for p in flow] + [p.t for p in density]
    if fat is not None:
        all_ts += [p.t for p in fat]
    grid = sorted({t for t in all_ts if t_start - 1e-6 <= t <= t_end + 1e-6})
    if not grid or grid[0] > t_start:
        grid = [t_start] + grid
    if grid[-1] < t_end:
        grid = grid + [t_end]
    times = np.array(grid, dtype=float)

    q = _interp(times, flow)
    rho = _interp(times, density)
    mass_rate = q * rho                      # kg/s

    if fat is None:
        total = float(_trapz(mass_rate, times))
        uq = _rel_uc_grid(times, flow, q)
        ur = _rel_uc_grid(times, density, rho)
    else:
        w = np.clip(_interp(times, fat), 0.0, 1.0)
        total = float(_trapz(mass_rate * w, times))
        uq = _rel_uc_grid(times, flow, q)
        ur = _rel_uc_grid(times, density, rho)
        uw = _rel_uc_grid(times, fat, w)
        # 脂肪质量相对不确定度（每个网格点）
        uq = np.sqrt(uq**2 + ur**2 + uw**2)
        # 质量速率项不再重复密度
        mass_rate_for_uc = np.abs(mass_rate * w)
        integrand_uc = mass_rate_for_uc * uq
        seg_uc = np.array([
            0.5 * (integrand_uc[i] + integrand_uc[i + 1]) * (times[i + 1] - times[i])
            for i in range(len(times) - 1)
        ])
        return IntegratedTotal(
            total,
            float(math.sqrt(float(np.sum(seg_uc**2)))),
            True,
            len(times),
            reasons,
            sorted(src),
        )

    integrand_uc = np.abs(mass_rate) * np.sqrt(uq**2 + ur**2)
    seg_uc = np.array([
        0.5 * (integrand_uc[i] + integrand_uc[i + 1]) * (times[i + 1] - times[i])
        for i in range(len(times) - 1)
    ])
    return IntegratedTotal(
        total,
        float(math.sqrt(float(np.sum(seg_uc**2)))),
        True,
        len(times),
        reasons,
        sorted(src),
    )
