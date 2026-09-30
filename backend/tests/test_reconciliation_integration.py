from datetime import datetime, timezone
import math

from app.db.models import Batch, Edge, Measurement, Node, Segment
from app.services.jobs import claim_next_job, execute_job
from app.services.topology import make_snapshot, problem_from_snapshot
from app.services.reconciliation import identifiability_report, solve

T0 = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 30, 8, 30, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 30, 9, tzinfo=timezone.utc)


def m(seg, target_type, target, metric, value, start, end=None, unit="kg/h",
      basis="wet", sigma=.01, range_code=None):
    return Measurement(segment_id=seg.id, target_type=target_type, target_id=target,
                       metric=metric, value=value, unit=unit, basis=basis,
                       uncertainty_type="stddev", uncertainty_value=sigma,
                       period_start=start, period_end=end, range_code=range_code)


def make_seed(db):
    b1 = Batch(code="A", name="A", status="active")
    b2 = Batch(code="B", name="B", status="active")
    db.add_all([b1, b2]); db.flush()
    sa = Segment(batch_id=b1.id, code="SA", kind="cream", window_start=T0, window_end=T2, version=1)
    sb = Segment(batch_id=b2.id, code="SB", kind="cross_batch", window_start=T0, window_end=T2, version=1)
    db.add_all([sa, sb]); db.flush()
    src = Node(segment_id=sa.id, code="RAW", name="raw", node_type="source")
    sep = Node(segment_id=sa.id, code="SEP", name="sep", node_type="process")
    tank = Node(segment_id=sa.id, code="TANK", name="tank", node_type="tank", include_inventory=True)
    sink = Node(segment_id=sa.id, code="SINK", name="sink", node_type="sink")
    later = Node(segment_id=sb.id, code="LATER", name="later", node_type="process")
    hold = Node(segment_id=sb.id, code="HOLD", name="hold", node_type="process")
    db.add_all([src, sep, tank, sink, later, hold]); db.flush()
    edges = []
    for args in [
        ("E1", src, sep, False), ("E2", sep, sink, False), ("E3", sep, tank, False),
        ("E4", tank, sink, False), ("E5", tank, later, True),
        ("E6", hold, tank, True), ("E7", later, hold, True),
    ]:
        e = Edge(code=args[0], name=args[0], source_node_id=args[1].id,
                 target_node_id=args[2].id, cross_batch=args[3])
        db.add(e); edges.append(e)
    db.flush()
    e1,e2,e3,e4,e5,e6,e7 = edges
    rows = []
    def half(seg, edge, q, fat=None):
        for s,e in ((T0,T1),(T1,T2)):
            rows.append(m(seg, "edge", edge.id, "mass_flow", q, s, e))
            if fat is not None:
                rows.append(m(seg, "edge", edge.id, "fat_fraction", fat, s, None, "fraction", sigma=.0001))
    half(sa,e1,1000,.048); half(sa,e2,900,0); half(sa,e3,100,.48); half(sa,e4,60,.5)
    rows += [m(sa, "edge", e5.id, "mass_flow", 40, T0, T1, range_code="low"),
             m(sa, "edge", e5.id, "mass_flow", 0, T1, T2, range_code="high"),
             m(sa, "edge", e5.id, "fat_fraction", .4, T0, None, "fraction", sigma=.0001)]
    for edge in (e6,e7):
        for s,e in ((T0,T1),(T1,T2)):
            rows.append(m(sb, "edge", edge.id, "mass_flow", 20, s, e))
            rows.append(m(sb, "edge", edge.id, "fat_fraction", .4, s, None, "fraction", sigma=.0001))
    rows += [
        m(sa, "node", tank.id, "mass", 100, T0, None, "kg", sigma=.01),
        m(sa, "node", tank.id, "fat_mass", 50, T0, None, "kg", sigma=.005),
        m(sa, "node", tank.id, "mass", 140, T2, None, "kg", sigma=.01),
        m(sa, "node", tank.id, "fat_mass", 68, T2, None, "kg", sigma=.005),
    ]
    db.add_all(rows); db.commit()
    return sa, sb, edges, tank


def run_snapshot(db, seg):
    snap = make_snapshot(db, seg, "reconciliation-1.0.0")
    problem, aggregates = problem_from_snapshot(snap)
    return problem, aggregates, solve(problem)


def test_seed_manual_mass_fat_closure_with_loop_and_tank_bottom(db_session):
    sa, sb, edges, tank = make_seed(db_session)
    problem, aggregates, result = run_snapshot(db_session, sa)
    assert result["identifiability"]["identified"] is True
    assert result["status"] == "succeeded"
    # Hand calculation: SEP 1000 = 900 + 100, fat 48 = 0 + 48.
    # TANK: 100 + 100 + 20 = 60 + 20 + 140; fat 50 + 48 + 8 = 30 + 8 + 8 + 68.
    assert result["closure_summary"]["max_abs_closed_kg"] < 1e-6
    assert result["closure_summary"]["max_abs_raw_kg"] < 1e-6
    edge_agg = {a["code"]: a for a in aggregates["edges"]}
    assert math.isclose(edge_agg["E5"]["mass"], 20)
    assert set(edge_agg["E5"]["range_hours"]) == {"low", "high"}


def test_underdetermined_loop_reports_missing_edge_and_interval_no_unique_result(db_session):
    sa, sb, edges, tank = make_seed(db_session)
    # The three cross-batch/cycle streams must all be unknown: one measured
    # stream would otherwise set the common circulation rate through node rows.
    cycle_edge_ids = {edges[4].id, edges[5].id, edges[6].id}
    rows = [x for x in db_session.query(Measurement).filter(Measurement.target_type == "edge",
                                                             Measurement.target_id.in_(cycle_edge_ids))]
    for row in rows:
        db_session.delete(row)
    db_session.commit()
    problem, aggregates, result = run_snapshot(db_session, sa)
    assert result["status"] == "underdetermined"
    assert result["identifiability"]["identified"] is False
    missing = result["identifiability"]["missing_measurement_sets"]
    assert missing
    names = {x["variable"] for x in missing[0]["measurements"]}
    assert any(any(code in n for code in ("E5", "E6", "E7")) for n in names)
    assert all(v["min"] >= 0 for v in missing[0]["allowed_intervals"].values())


def test_stable_window_change_marks_slow_old_job_superseded(db_session):
    sa, sb, edges, tank = make_seed(db_session)
    snap = make_snapshot(db_session, sa, "reconciliation-1.0.0")
    from app.db.models import Job
    job = Job(segment_id=sa.id, status="queued", input_version=sa.version,
              algorithm_version="reconciliation-1.0.0", input_summary=snap["input_summary"],
              input_snapshot=snap)
    db_session.add(job); db_session.commit()
    claimed = claim_next_job(db_session, "w1")
    sa.window_end = T2  # keep window valid
    sa.window_start = T1
    sa.version = 2
    db_session.commit()
    finished = execute_job(db_session, claimed.id)
    assert finished.status == "superseded"
    assert finished.result is None
