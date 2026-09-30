"""Mass and fat conservation reconciliation.

Variables are physical window totals:
* two variables per connected material stream: total mass and total fat mass;
* two initial and two final variables per inventory-bearing node.

Tank bottom material is not a special carry-over heuristic: initial and final
inventory appear in the same node balance. Edges crossing segment or batch
boundaries are ordinary directed edges, so回流 cycles and cross-batch returns
are included in the same linear conservation system.
"""
from dataclasses import dataclass
from itertools import combinations
import math
import numpy as np
from scipy.optimize import linprog, minimize

EPS = 1e-8
UNMEASURED_SIGMA = 1e6


@dataclass
class ReconciliationProblem:
    variable_names: list[str]
    kinds: list[str]
    refs: list[str]
    measurements: list[float | None]
    sigmas: list[float | None]
    lower_bounds: list[float]
    upper_bounds: list[float]
    A: np.ndarray
    b: np.ndarray
    node_labels: list[str]
    component_labels: list[str]
    topology: dict
    aggregates: dict


def _add_var(names, kinds, refs, measurements, sigmas, lbs, ubs, name, kind, ref, value, sigma):
    idx = len(names)
    names.append(name)
    kinds.append(kind)
    refs.append(ref)
    measurements.append(value)
    sigmas.append(sigma)
    lbs.append(EPS if "fat" in kind or "mass" in kind else 0.0)
    ubs.append(math.inf)
    return idx


def build_problem(aggregates: dict, nodes: list, edges: list, inventories: dict) -> ReconciliationProblem:
    names, kinds, refs, meas, sigmas, lbs, ubs = [], [], [], [], [], [], []
    edge_mass, edge_fat = {}, {}
    for e in edges:
        agg = aggregates["edges"].get(e.id)
        m = _add_var(names, kinds, refs, meas, sigmas, lbs, ubs,
                     f"edge:{e.code}:mass", "edge_mass", f"edge:{e.id}",
                     getattr(agg, "mass", None), getattr(agg, "mass_sigma", None))
        f = _add_var(names, kinds, refs, meas, sigmas, lbs, ubs,
                     f"edge:{e.code}:fat_mass", "edge_fat_mass", f"edge:{e.id}",
                     getattr(agg, "fat_mass", None), getattr(agg, "fat_sigma", None))
        edge_mass[e.id] = m
        edge_fat[e.id] = f

    inv_var = {}
    for n in nodes:
        if not n.include_inventory:
            continue
        inv = inventories.get(n.id)
        inv_var[n.id] = {}
        for phase in ("initial", "final"):
            for component, attr, sigma_attr in (
                ("mass", "mass", "sigma"),
                ("fat_mass", "fat", "fat_sigma"),
            ):
                val = getattr(inv, f"{phase}_{attr}", None) if inv else None
                sigma = getattr(inv, f"{phase}_{sigma_attr}", None) if inv else None
                idx = _add_var(names, kinds, refs, meas, sigmas, lbs, ubs,
                               f"node:{n.code}:{phase}:{component}", f"inventory_{phase}_{component}",
                               f"node:{n.id}", val, sigma)
                inv_var[n.id][(phase, component)] = idx

    A_rows, labels, component_labels = [], [], []
    balance_nodes = [n for n in nodes if n.node_type not in ("source", "sink")]
    for n in balance_nodes:
        for component, emap in (("mass", edge_mass), ("fat_mass", edge_fat)):
            row = np.zeros(len(names))
            for e in edges:
                if e.source_node_id == n.id:
                    row[emap[e.id]] -= 1.0
                if e.target_node_id == n.id:
                    row[emap[e.id]] += 1.0
            if n.id in inv_var:
                row[inv_var[n.id][("initial", component)]] += 1.0
                row[inv_var[n.id][("final", component)]] -= 1.0
            A_rows.append(row)
            labels.append(f"{n.code}({n.node_type})")
            component_labels.append(component)
    A = np.asarray(A_rows)
    b = np.zeros(len(A_rows))
    topology = {
        "nodes": [{"id": n.id, "code": n.code, "type": n.node_type,
                   "include_inventory": n.include_inventory} for n in nodes],
        "edges": [{"id": e.id, "code": e.code, "source": e.source_node_id,
                   "target": e.target_node_id, "cross_batch": e.cross_batch} for e in edges],
    }
    return ReconciliationProblem(names, kinds, refs, meas, sigmas, lbs, ubs, A, b, labels,
                                 component_labels, topology, aggregates)


def candidate_missing(p: ReconciliationProblem) -> list[dict]:
    """Identify minimal currently-unmeasured variables needed for rank completion.

    Measurement rows are included so the check represents a constrained WLS
    problem, not merely the unconstrained graph nullspace.
    """
    n = len(p.variable_names)
    measured_idx = [i for i, v in enumerate(p.measurements) if v is not None]
    M = np.vstack([p.A, np.eye(n)[measured_idx, :]])
    current = np.linalg.matrix_rank(M)
    deficit = n - current
    unmeasured = [i for i, v in enumerate(p.measurements) if v is None]
    minimal = []
    # Typical cases need very few measurements; cap combination depth to avoid
    # combinatorial explosion on large process graphs.
    for depth in range(1, min(deficit, len(unmeasured), 4) + 1):
        for combo in combinations(unmeasured, depth):
            C = np.eye(n)[list(combo), :]
            if np.linalg.matrix_rank(np.vstack([M, C])) == n:
                minimal.append(list(combo))
        if minimal:
            break
    result = []
    for combo in minimal:
        bounds = allowed_interval(p, list(combo), fixed_measured=measured_idx)
        result.append({
            "measurements": [
                {"variable": p.variable_names[i], "kind": p.kinds[i], "ref": p.refs[i]}
                for i in combo
            ],
            "allowed_intervals": bounds,
        })
    return result


def allowed_interval(p: ReconciliationProblem, variables: list[int],
                     fixed_measured: list[int] | None = None) -> dict[str, dict]:
    """Solve LPs for candidate values after adding those candidate measurements.

    Other currently unmeasured variables remain free within physical bounds.
    Fixing them to zero would describe a different, often infeasible process.
    """
    out = {}
    measured_idx = fixed_measured or [i for i, v in enumerate(p.measurements) if v is not None]
    n = len(p.variable_names)
    Aeq = np.vstack([p.A, np.eye(n)[measured_idx, :]])
    beq = np.concatenate([p.b, np.asarray([p.measurements[i] for i in measured_idx])])
    bounds = [(p.lower_bounds[i], p.upper_bounds[i]) for i in range(n)]
    for idx in variables:
        values = {}
        for sense in ("min", "max"):
            c = np.zeros(n)
            c[idx] = 1 if sense == "min" else -1
            res = linprog(c, A_eq=Aeq, b_eq=beq, bounds=bounds, method="highs")
            if not res.success:
                values[sense] = None
            else:
                values[sense] = float(res.x[idx])
        out[p.variable_names[idx]] = {
            "min": values["min"],
            "max": values["max"],
            "unit": "kg",
        }
    return out


def identifiability_report(p: ReconciliationProblem) -> dict:
    n = len(p.variable_names)
    measured_idx = [i for i, v in enumerate(p.measurements) if v is not None]
    M = np.vstack([p.A, np.eye(n)[measured_idx, :]])
    rank = int(np.linalg.matrix_rank(M))
    missing = candidate_missing(p)
    return {
        "identified": rank == n,
        "rank": rank,
        "variables": n,
        "rank_deficit": n - rank,
        "missing_measurement_sets": missing,
        "policy": "under-determined models return missing measurements and feasible intervals; no unique graph is produced",
    }


def solve(p: ReconciliationProblem) -> dict:
    ident = identifiability_report(p)
    if not ident["identified"]:
        return {"status": "underdetermined", "identifiability": ident}

    z = np.asarray([v if v is not None else 0.0 for v in p.measurements], dtype=float)
    sigma = np.asarray([s if s is not None else UNMEASURED_SIGMA for s in p.sigmas], dtype=float)
    sigma = np.maximum(sigma, 1e-9)
    W = np.diag(1.0 / sigma**2)

    def objective(x):
        d = x - z
        return float(d @ W @ d)

    def gradient(x):
        return 2.0 * W @ (x - z)

    constraints = {"type": "eq", "fun": lambda x: p.A @ x - p.b, "jac": lambda x: p.A}
    bounds = list(zip(p.lower_bounds, p.upper_bounds))
    x0 = np.maximum(z, EPS)
    res = minimize(objective, x0, jac=gradient, method="SLSQP", bounds=bounds,
                   constraints=[constraints],
                   options={"maxiter": 300, "ftol": 1e-12})
    x = res.x
    closure = p.A @ x - p.b
    raw_closure = p.A @ z
    variables = []
    for i, name in enumerate(p.variable_names):
        variables.append({
            "name": name,
            "kind": p.kinds[i],
            "ref": p.refs[i],
            "raw": None if p.measurements[i] is None else float(z[i]),
            "raw_sigma": None if p.sigmas[i] is None else float(sigma[i]),
            "adjusted": float(x[i]),
            "correction": float(x[i] - z[i]) if p.measurements[i] is not None else None,
        })
    node_residuals = [
        {"node": p.node_labels[i], "component": p.component_labels[i],
         "raw_closure_kg": float(raw_closure[i]), "closed_closure_kg": float(closure[i])}
        for i in range(len(p.b))
    ]
    total_abs_raw = float(np.sum(np.abs(raw_closure)))
    total_abs_closed = float(np.sum(np.abs(closure)))
    return {
        "status": "succeeded",
        "solver_success": bool(res.success),
        "solver_message": res.message,
        "objective": objective(x),
        "identifiability": ident,
        "variables": variables,
        "node_residuals": node_residuals,
        "closure_summary": {
            "sum_abs_raw_kg": total_abs_raw,
            "sum_abs_closed_kg": total_abs_closed,
            "max_abs_raw_kg": float(np.max(np.abs(raw_closure))),
            "max_abs_closed_kg": float(np.max(np.abs(closure))),
        },
        "disclaimer": "This is a reconciliation/accounting result only; it does not recommend blend ratios or control actions.",
    }
