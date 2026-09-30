from datetime import datetime, timedelta, timezone

from app.db.models import Batch, Segment
from tests.test_reconciliation_integration import make_seed

T0 = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=30)
T2 = T0 + timedelta(hours=1)


def _measurement(seg, edge_id, metric, value, start, end=None, unit="kg/h",
                 basis="wet", sigma=.01, range_code=None):
    return {
        "target_type": "edge", "target_id": edge_id, "metric": metric, "value": value,
        "unit": unit, "basis": basis, "uncertainty_type": "stddev",
        "uncertainty_value": sigma, "period_start": start.isoformat(),
        "period_end": end.isoformat() if end else None, "range_code": range_code
    }


def test_full_api_flow_and_late_input_cannot_overwrite_current(client, db_session):
    sa, sb, edges, tank = make_seed(db_session)
    sid = sa.id
    pre = client.post(f"/api/segments/{sid}/precheck").json()
    assert pre["identifiability"]["identified"] is True

    job = client.post(f"/api/segments/{sid}/jobs").json()
    claim = client.post("/api/worker/claim", json={"worker_id": "w0"}).json()
    assert claim["id"] == job["id"]
    first = client.post(f"/api/worker/jobs/{claim['id']}/complete").json()
    assert first["status"] == "succeeded"

    # The old frozen job is missing one fat sample. That under-determined input
    # is enqueued; the delayed laboratory point arrives after claim and bumps v.
    from app.db.models import Measurement
    for row in db_session.query(Measurement).filter_by(target_type="edge",
                                                        target_id=edges[3].id,
                                                        metric="fat_fraction"):
        db_session.delete(row)
    db_session.commit()
    # Re-enqueue the deliberately incomplete frozen input.
    old_job = client.post(f"/api/segments/{sid}/jobs").json()
    old_claim = client.post("/api/worker/claim", json={"worker_id": "w1"}).json()
    assert old_claim["id"] == old_job["id"]
    late = client.post(f"/api/segments/{sid}/measurements", json=_measurement(
        sa, edges[3].id, "fat_fraction", .5, T0, None, "fraction", sigma=.0001))
    assert late.status_code == 201
    completed = client.post(f"/api/worker/jobs/{old_claim['id']}/complete").json()
    assert completed["status"] == "superseded"
    assert client.get(f"/api/segments/{sid}/current-result").status_code == 404

    job2 = client.post(f"/api/segments/{sid}/jobs").json()
    claim2 = client.post("/api/worker/claim", json={"worker_id": "w2"}).json()
    assert claim2["id"] == job2["id"]
    done = client.post(f"/api/worker/jobs/{claim2['id']}/complete").json()
    assert done["status"] == "succeeded"
    current = client.get(f"/api/segments/{sid}/current-result").json()
    assert current["job_id"] == job2["id"]
    assert current["result"]["closure_summary"]["max_abs_closed_kg"] < 1e-6

    sign = client.post(f"/api/jobs/{job2['id']}/signoff", json={"engineer": "Alice"}).json()
    assert sign["input_summary"] == current["input_summary"]
    assert len(sign["signature"]) == 32
    current = client.get(f"/api/segments/{sid}/current-result").json()
    assert current["signoff"]["engineer"] == "Alice"


def test_precheck_underdetermined_does_not_enforce_unique_graph(client, db_session):
    sa, sb, edges, tank = make_seed(db_session)
    cycle = {edges[4].id, edges[5].id, edges[6].id}
    for m in list(db_session.query(__import__("app.db.models", fromlist=["Measurement"]).Measurement)):
        if m.target_type == "edge" and m.target_id in cycle:
            db_session.delete(m)
    db_session.commit()
    pre = client.post(f"/api/segments/{sa.id}/precheck").json()
    assert pre["identifiability"]["identified"] is False
    assert pre["identifiability"]["rank_deficit"] >= 1
    assert pre["identifiability"]["missing_measurement_sets"]
    notes = client.get("/api/engineering-notes").json()
    assert "No re-blend" in notes["safety_scope"]
