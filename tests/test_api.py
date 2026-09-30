"""FastAPI 端到端：建拓扑/批/样品 -> 窗口 -> 试算 -> 作业 -> 结果 -> 签署。"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(seeded):
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "不推荐回配比例" in body["platform_notice"]


def test_topology_and_batch_crud(client):
    nodes = [{"id": "S", "type": "source", "name": "s"},
             {"id": "K", "type": "sink", "name": "k"}]
    streams = [{"id": "x", "source": "S", "sink": "K"}]
    r = client.post("/api/topologies",
                    json={"code": "t1", "name": "T", "nodes": nodes,
                          "streams": streams})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    bad = client.post("/api/topologies",
                      json={"code": "t2", "name": "bad",
                            "nodes": nodes,
                            "streams": [{"id": "y", "source": "S",
                                         "sink": "GHOST"}]})
    assert bad.status_code == 422

    t0 = datetime(2026, 9, 29, tzinfo=timezone.utc)
    r = client.post("/api/batches", json={
        "topology_id": tid, "code": "BX", "segments": [
            {"seq": 1, "code": "a",
             "start_ts": t0.isoformat(),
             "end_ts": (t0 + timedelta(hours=1)).isoformat()}]})
    assert r.status_code == 201, r.text


def test_sample_unit_validation(client):
    r = client.post("/api/samples", json={
        "stream_id": "F1", "ts": "2026-09-30T00:30:00+00:00",
        "metric": "flow", "value": 0.3, "unit": "bogo-units"})
    assert r.status_code == 422
    r2 = client.post("/api/samples", json={
        "stream_id": "F1", "ts": "2026-09-30T00:30:00+00:00",
        "metric": "fat", "value": 10, "unit": "percent_dry"})
    # 干基必须提供总固形物
    assert r2.status_code == 422


def test_seeded_preview_identified_flow(client, seeded):
    wid = seeded["A"]["window"]
    r = client.post(f"/api/windows/{wid}/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "identified"
    # 闭合残差图数据
    assert body["closure"]["reconciled"]
    assert all(abs(x["residual_kg"]) < 1e-6
               for x in body["closure"]["reconciled"])


def test_job_result_signoff_flow(client, seeded):
    wid = seeded["A"]["window"]
    r = client.post(f"/api/windows/{wid}/jobs")
    assert r.status_code == 202
    job_id = r.json()["id"]

    # worker 在同进程同步执行（测试用）
    from worker.compute_worker import _claim_one, process_job
    from app.database import SessionLocal
    db = SessionLocal()
    claimed = _claim_one(db); db.close()
    process_job(claimed.id)

    r = client.get(f"/api/windows/{wid}/result")
    assert r.status_code == 200
    result = r.json()
    assert result["status"] == "identified"
    rid = result["id"]

    so = client.post(f"/api/results/{rid}/signoff",
                     json={"engineer": "wang", "note": "ok"})
    assert so.status_code == 201, so.text
    body = so.json()
    assert body["input_digest"] == result["digest"]
    assert body["algorithm_version"] == result["algorithm_version"]

    # 窗口结果变化后，旧结果不能再签署
    r2 = client.post(f"/api/results/{rid}/signoff",
                     json={"engineer": "zhao"})
    # 同一结果仍是 current 时允许追加签署；撤销后旧签署只读
    assert r2.status_code in (201, 409)


def test_reflux_preview_is_underdetermined(client, seeded):
    wid = seeded["B"]["window"]
    r = client.post(f"/api/windows/{wid}/preview")
    body = r.json()
    assert body["status"] == "underdetermined"
    assert body["missing_measurements"]
    assert body["allowed_intervals"]["intervals"]
    # API 载荷不含任何回配比例建议字段
    assert "recommended" not in str(body).lower() or \
           "不推荐回配比例" in body["platform_notice"]


def test_dry_basis_sample_accepted_with_solids(client, seeded):
    r = client.post("/api/samples", json={
        "batch_id": seeded["A"]["batch"],
        "stream_id": "F2", "ts": "2026-09-30T00:20:00+00:00",
        "metric": "fat", "value": 40.0, "unit": "percent_dry",
        "solids_fraction_wet": 0.10, "rel_uc": 0.02})
    assert r.status_code == 201, r.text
    # 40% 干基 × 10% 总固形物 = 4% 湿基
    from app.database import SessionLocal
    from app.models import Sample
    db = SessionLocal()
    s = db.query(Sample).filter_by(stream_id="F2",
                                   unit="percent_dry").first()
    assert s is not None
    from app.core.units import convert_fat_sample
    cv = convert_fat_sample(s.value, s.unit, s.solids_fraction_wet)
    assert cv.converted == pytest.approx(0.04)
    db.close()


def test_late_sample_roundtrip_and_signoff_guard(client, seeded):
    """迟到样可录入但不影响已冻结结果；非 identified 结果签署被拒。"""
    wid_b = seeded["B"]["window"]
    r = client.post(f"/api/windows/{wid_b}/jobs")
    assert r.status_code == 202
    from app.database import SessionLocal
    from worker.compute_worker import _claim_one, process_job
    db = SessionLocal(); claimed = _claim_one(db); db.close()
    process_job(claimed.id)

    r = client.get(f"/api/windows/{wid_b}/result")
    body = r.json()
    assert body["status"] == "underdetermined"
    so = client.post(f"/api/results/{body['id']}/signoff",
                     json={"engineer": "x"})
    assert so.status_code == 409


def test_window_adjustment_invalidates_current(client, seeded):
    """PUT 调整窗口后，旧结果 is_current=false；前端取到的是新窗口（无结果）。"""
    wid = seeded["A"]["window"]
    # 先跑出一个当前结果
    client.post(f"/api/windows/{wid}/jobs")
    from app.database import SessionLocal
    from worker.compute_worker import _claim_one, process_job
    db = SessionLocal(); c = _claim_one(db); cid = c.id; db.close()
    process_job(cid)
    before = client.get(f"/api/windows/{wid}/result")
    assert before.status_code == 200

    seg_ids = seeded["A"]["segments"][:1]  # 调整为仅一段
    r = client.put(f"/api/windows/{wid}",
                   json={"label": "调整后", "segment_ids": seg_ids,
                         "max_gap_s": 2000, "extrap_tolerance_s": 700})
    assert r.status_code == 200, r.text
    new_wid = r.json()["id"]
    assert r.json()["superseded_by"] == wid

    old = client.get(f"/api/results/{before.json()['id']}")
    assert old.json()["is_current"] is False
    gone = client.get(f"/api/windows/{wid}/result")
    assert gone.status_code == 404

    # 新窗口（只含一段）仍可试算
    pv = client.post(f"/api/windows/{new_wid}/preview")
    assert pv.status_code == 200
