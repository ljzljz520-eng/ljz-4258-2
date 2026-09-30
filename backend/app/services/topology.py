import hashlib
import json
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Edge, Measurement, Node, Segment
from app.services.aggregation import aggregate_edges, aggregate_inventories
from app.services.reconciliation import ReconciliationProblem, build_problem


def _iso(obj):
    if isinstance(obj, datetime):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=timezone.utc)
        return obj.astimezone(timezone.utc).isoformat()
    return obj


def jsonable(obj):
    if isinstance(obj, datetime):
        return _iso(obj)
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    return obj


def parse_dt(value):
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_iso)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scope_for_segment(db: Session, segment: Segment):
    local_nodes = db.scalars(select(Node).where(Node.segment_id == segment.id)).all()
    local_ids = {n.id for n in local_nodes}
    edges = db.scalars(
        select(Edge).where(Edge.source_node_id.in_(local_ids) | Edge.target_node_id.in_(local_ids))
    ).all()
    endpoint_ids = {x for e in edges for x in (e.source_node_id, e.target_node_id)}
    boundary_nodes = db.scalars(select(Node).where(Node.id.in_(endpoint_ids))).all() if endpoint_ids else []
    # A cross-batch edge opens the complete connected neighboring segment(s).
    # Internal edges in that segment are needed to identify return loops.
    segment_ids = {n.segment_id for n in boundary_nodes}
    nodes = db.scalars(select(Node).where(Node.segment_id.in_(segment_ids))).all() if segment_ids else []
    node_ids = {n.id for n in nodes}
    edges = db.scalars(select(Edge).where(
        Edge.source_node_id.in_(node_ids) & Edge.target_node_id.in_(node_ids)
    )).all() if node_ids else []
    measurements = db.scalars(
        select(Measurement).where(Measurement.segment_id.in_(segment_ids))
    ).all()
    # Only measurements attached to scoped nodes/edges enter the frozen snapshot.
    edge_ids = {e.id for e in edges}
    node_ids = {n.id for n in nodes}
    measurements = [
        m for m in measurements
        if (m.target_type == "edge" and m.target_id in edge_ids)
        or (m.target_type == "node" and m.target_id in node_ids)
    ]
    return nodes, edges, measurements


def make_snapshot(db: Session, segment: Segment, algorithm_version: str) -> dict:
    nodes, edges, measurements = scope_for_segment(db, segment)
    segments = db.scalars(select(Segment).where(Segment.id.in_({n.segment_id for n in nodes}))).all()
    payload = {
        "algorithm_version": algorithm_version,
        "frozen_at": datetime.now(timezone.utc),
        "segment": {
            "id": segment.id, "code": segment.code, "version": segment.version,
            "window_start": segment.window_start, "window_end": segment.window_end,
        },
        "segments": [
            {"id": s.id, "batch_id": s.batch_id, "code": s.code, "version": s.version,
             "window_start": s.window_start, "window_end": s.window_end}
            for s in segments
        ],
        "nodes": [
            {"id": n.id, "segment_id": n.segment_id, "code": n.code, "name": n.name,
             "node_type": n.node_type, "include_inventory": n.include_inventory}
            for n in nodes
        ],
        "edges": [
            {"id": e.id, "code": e.code, "name": e.name,
             "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
             "cross_batch": e.cross_batch}
            for e in edges
        ],
        "measurements": [
            {"id": m.id, "segment_id": m.segment_id, "target_type": m.target_type,
             "target_id": m.target_id, "metric": m.metric, "value": m.value, "unit": m.unit,
             "basis": m.basis, "uncertainty_type": m.uncertainty_type,
             "uncertainty_value": m.uncertainty_value, "period_start": m.period_start,
             "period_end": m.period_end, "observed_at": m.observed_at,
             "range_code": m.range_code, "note": m.note}
            for m in sorted(measurements, key=lambda x: (x.segment_id, x.target_type, x.target_id,
                                                         x.metric, x.period_start, x.id))
        ],
    }
    payload["input_summary"] = sha256_text(canonical_json({k: payload[k] for k in (
        "algorithm_version", "segment", "segments", "nodes", "edges", "measurements")}))
    return jsonable(payload)


def problem_from_snapshot(snapshot: dict):
    """Build aggregate problem from a frozen snapshot, using selected segment window."""
    class N:
        def __init__(self, **kw): self.__dict__.update(kw)

    raw_seg = dict(snapshot["segment"])
    raw_seg["window_start"] = parse_dt(raw_seg["window_start"])
    raw_seg["window_end"] = parse_dt(raw_seg["window_end"])
    seg = N(**raw_seg)
    nodes = [N(**n) for n in snapshot["nodes"]]
    edges = [N(**e) for e in snapshot["edges"]]
    raw_measurements = []
    for item in snapshot["measurements"]:
        x = dict(item)
        x["period_start"] = parse_dt(x["period_start"])
        x["period_end"] = parse_dt(x["period_end"])
        x["observed_at"] = parse_dt(x.get("observed_at"))
        raw_measurements.append(N(**x))
    measurements = raw_measurements
    edge_codes = {e.id: e.code for e in edges}
    edge_aggs = aggregate_edges([e.id for e in edges], measurements,
                                seg.window_start, seg.window_end, edge_codes)
    inv_aggs = aggregate_inventories(nodes, measurements, seg.window_start, seg.window_end)
    aggregates = {
        "edges": [edge_aggs[e.id].__dict__ for e in edges],
        "inventories": [v.__dict__ for v in inv_aggs.values()],
    }
    problem = build_problem({"edges": edge_aggs}, nodes, edges, inv_aggs)
    return problem, aggregates


def input_signature(snapshot: dict, secret: str) -> str:
    body = canonical_json({"input_summary": snapshot["input_summary"],
                           "algorithm_version": snapshot["algorithm_version"]})
    return sha256_text(body + "|" + secret)[:32]
