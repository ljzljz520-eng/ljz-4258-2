from dataclasses import dataclass, field
from datetime import datetime
import math

from app.services.alignment import build_intervals, uncovered_hours, split_ranges
from app.services.units import convert_value, factor, dry_to_wet_fraction

POINT_METRICS = {"density", "fat_fraction", "solids_fraction"}
MIN_SIGMA = 1e-9


@dataclass
class EdgeAggregate:
    edge_id: int
    code: str
    mass: float | None = None
    mass_sigma: float | None = None
    fat_mass: float | None = None
    fat_sigma: float | None = None
    measured_mass: bool = False
    measured_fat_mass: bool = False
    coverage_hours: float = 0.0
    uncovered_hours: float = 0.0
    range_hours: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)


@dataclass
class InventoryAggregate:
    node_id: int
    initial_mass: float | None = None
    initial_sigma: float | None = None
    final_mass: float | None = None
    final_sigma: float | None = None
    initial_fat: float | None = None
    initial_fat_sigma: float | None = None
    final_fat: float | None = None
    final_fat_sigma: float | None = None
    measured_initial_mass: bool = False
    measured_final_mass: bool = False
    measured_initial_fat: bool = False
    measured_final_fat: bool = False
    flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Slice:
    start: datetime
    end: datetime
    flow: object
    density: object | None
    fat: object | None = None
    solids: object | None = None

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600.0


def _normalized_row(r):
    class Row:
        pass
    out = Row()
    out.id = r.id
    out.metric = r.metric
    out.period_start = r.period_start
    out.period_end = r.period_end
    out.range_code = r.range_code
    out.basis = r.basis
    out.value = convert_value(r.value, r.unit)
    if r.uncertainty_type == "relative":
        raw_sigma = abs(r.value * r.uncertainty_value)
    elif r.uncertainty_type == "expanded_95":
        raw_sigma = r.uncertainty_value / 1.96
    else:
        raw_sigma = r.uncertainty_value
    out.uncertainty_value = raw_sigma * factor(r.unit)
    return out


def _covering(intervals, start, end):
    return next((i for i in intervals if i.start <= start and end <= i.end), None)


def _slices(flows, densities, fats, solids, is_volume):
    boundaries = {iv.start for fl in flows for iv in [fl]}
    boundaries.update(iv.end for iv in flows)
    if is_volume:
        for arr in (densities, fats, solids):
            for iv in arr:
                boundaries.update((iv.start, iv.end))
    else:
        for arr in (fats, solids):
            for iv in arr:
                boundaries.update((iv.start, iv.end))
    boundaries = sorted(b for b in boundaries if not any(False for _ in ()))
    out = []
    for start, end in zip(boundaries, boundaries[1:]):
        fl = _covering(flows, start, end)
        if not fl:
            continue
        den = _covering(densities, start, end) if is_volume else None
        if is_volume and den is None:
            continue
        fat = _covering(fats, start, end) if fats else None
        sol = _covering(solids, start, end) if solids else None
        out.append(Slice(start, end, fl, den, fat, sol))
    return out


def aggregate_edges(edge_ids: list[int], measurements, window_start: datetime, window_end: datetime,
                    edge_codes: dict[int, str] | None = None) -> dict[int, EdgeAggregate]:
    by_edge: dict[int, list] = {}
    for raw in measurements:
        if raw.target_type == "edge" and raw.target_id in edge_ids:
            by_edge.setdefault(raw.target_id, []).append(_normalized_row(raw))

    out = {}
    for edge_id in edge_ids:
        agg = EdgeAggregate(edge_id=edge_id, code=(edge_codes or {}).get(edge_id, str(edge_id)))
        groups = build_intervals(by_edge.get(edge_id, []), window_start, window_end, POINT_METRICS)

        for metric, attr in (("mass", "mass"), ("fat_mass", "fat_mass")):
            direct = groups.get(metric, [])
            if direct:
                vals = [iv.value for iv in direct]
                sigma = math.sqrt(sum(max(iv.sigma, MIN_SIGMA) ** 2 for iv in direct))
                setattr(agg, attr, sum(vals))
                setattr(agg, f"{attr}_sigma", sigma)
                setattr(agg, f"measured_{'mass' if metric == 'mass' else 'fat_mass'}", True)

        volume_flows = groups.get("volume_flow", [])
        mass_flows = groups.get("mass_flow", [])
        flows = mass_flows or volume_flows
        is_volume = not mass_flows and bool(volume_flows)
        densities = groups.get("density", [])
        fats = groups.get("fat_fraction", [])
        solids = groups.get("solids_fraction", [])
        agg.range_hours = split_ranges(flows)
        agg.coverage_hours = sum(agg.range_hours.values())
        agg.uncovered_hours = uncovered_hours(flows, window_start, window_end)

        slices = _slices(flows, densities, fats, solids, is_volume) if flows else []
        if slices and not agg.measured_mass:
            mass, mass_var = 0.0, 0.0
            for s in slices:
                rho = s.density.value if is_volume else 1.0
                m = s.flow.value * rho * s.hours
                mass += m
                if is_volume:
                    mass_var += ((rho * s.hours * s.flow.sigma) ** 2 +
                                 (s.flow.value * s.hours * s.density.sigma) ** 2)
                else:
                    mass_var += (s.hours * s.flow.sigma) ** 2
            agg.mass, agg.mass_sigma = mass, math.sqrt(max(mass_var, MIN_SIGMA**2))
            agg.measured_mass = True

        if slices and not agg.measured_fat_mass:
            fat_total, fat_var = 0.0, 0.0
            complete = True
            dry_missing = False
            for s in slices:
                if s.fat is None:
                    complete = False
                    break
                solids_fraction = None
                if s.fat.basis == "dry":
                    if s.solids is None:
                        dry_missing = True
                        complete = False
                        break
                    solids_fraction = s.solids.value
                x = dry_to_wet_fraction(s.fat.value, solids_fraction) if s.fat.basis == "dry" else s.fat.value
                rho = s.density.value if is_volume else 1.0
                fm = s.flow.value * rho * x * s.hours
                fat_total += fm
                fat_var += ((rho * x * s.hours * s.flow.sigma) ** 2 +
                            (s.flow.value * rho * s.hours * s.fat.sigma) ** 2)
                if is_volume:
                    fat_var += (s.flow.value * x * s.hours * s.density.sigma) ** 2
                if s.fat.basis == "dry":
                    fat_var += (s.flow.value * rho * s.fat.value * s.hours * s.solids.sigma) ** 2
            if complete:
                agg.fat_mass, agg.fat_sigma = fat_total, math.sqrt(max(fat_var, MIN_SIGMA**2))
                agg.measured_fat_mass = True
            if dry_missing:
                agg.flags.append("dry_fat_without_coincident_solids")
        if agg.uncovered_hours > 0:
            agg.flags.append("uncovered_flow")
        if len(agg.range_hours) > 1:
            agg.flags.append("range_switch")
        out[edge_id] = agg
    return out


def aggregate_inventories(nodes, measurements, window_start: datetime, window_end: datetime) -> dict[int, InventoryAggregate]:
    by_node: dict[int, list] = {}
    for raw in measurements:
        if raw.target_type == "node":
            by_node.setdefault(raw.target_id, []).append(raw)
    out = {}
    for n in nodes:
        if not n.include_inventory:
            continue
        inv = InventoryAggregate(node_id=n.id)
        for raw in by_node.get(n.id, []):
            if raw.period_start not in (window_start, window_end):
                inv.flags.append(f"inventory_outside_boundary:{raw.id}")
                continue
            phase = "initial" if raw.period_start == window_start else "final"
            r = _normalized_row(raw)
            if r.metric == "mass":
                setattr(inv, f"{phase}_mass", r.value)
                setattr(inv, f"{phase}_sigma", max(r.uncertainty_value, MIN_SIGMA))
                setattr(inv, f"measured_{phase}_mass", True)
            elif r.metric == "fat_mass":
                setattr(inv, f"{phase}_fat", r.value)
                setattr(inv, f"{phase}_fat_sigma", max(r.uncertainty_value, MIN_SIGMA))
                setattr(inv, f"measured_{phase}_fat", True)
        out[n.id] = inv
    return out
