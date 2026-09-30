"""Idempotent deterministic seed case.

The values are hand-checkable over one hour and include:
* a cream/skim separation and a tank with old bottom material;
* a stream sent to a later batch and returned, forming a cross-batch loop;
* flow meter range switching;
* point fat samples with a coarser time grid than flow/density.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Batch, CalcVersion, Edge, Job, Measurement, Node, Segment
from app.db.session import SessionLocal

T0 = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 30, 8, 30, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)


def edge_measurement(segment, edge, metric, value, start, end=None, unit="kg/h",
                     basis="wet", sigma=0.01, range_code=None):
    return Measurement(
        segment_id=segment.id, target_type="edge", target_id=edge.id, metric=metric,
        value=value, unit=unit, basis=basis, uncertainty_type="stddev",
        uncertainty_value=sigma, period_start=start, period_end=end,
        range_code=range_code,
    )


def inventory_measurement(segment, node, metric, value, as_of, sigma=0.01):
    return Measurement(
        segment_id=segment.id, target_type="node", target_id=node.id, metric=metric,
        value=value, unit="kg", basis="wet", uncertainty_type="stddev",
        uncertainty_value=sigma, period_start=as_of, period_end=None,
    )


def seed():
    db = SessionLocal()
    try:
        settings = get_settings()
        if not db.scalar(select(CalcVersion).where(CalcVersion.version == settings.algorithm_version)):
            db.add(CalcVersion(version=settings.algorithm_version,
                               description="Linear mass/fat conservation, interval-aligned weighted least squares"))
        if db.scalar(select(Batch).where(Batch.code == "B-DEMO-A")):
            return "seed already present"

        batch_a = Batch(code="B-DEMO-A", name="Morning separation A", status="active")
        batch_b = Batch(code="B-DEMO-B", name="Cross-batch return B", status="active")
        db.add_all([batch_a, batch_b])
        db.flush()
        seg_a = Segment(batch_id=batch_a.id, code="SEP-A", kind="cream",
                        window_start=T0, window_end=T2)
        seg_b = Segment(batch_id=batch_b.id, code="RET-B", kind="cross_batch",
                        window_start=T0, window_end=T2)
        db.add_all([seg_a, seg_b]); db.flush()

        src = Node(segment_id=seg_a.id, code="RAW", name="Raw milk source", node_type="source")
        sep = Node(segment_id=seg_a.id, code="SEP", name="Separator", node_type="process")
        tank = Node(segment_id=seg_a.id, code="TANK", name="Cream balance tank",
                    node_type="tank", include_inventory=True)
        sink = Node(segment_id=seg_a.id, code="SINK", name="Cream product sink", node_type="sink")
        later = Node(segment_id=seg_b.id, code="LATER", name="Later batch receiver", node_type="process")
        hold = Node(segment_id=seg_b.id, code="HOLD", name="Cross-batch hold/return", node_type="process")
        db.add_all([src, sep, tank, sink, later, hold]); db.flush()

        e1 = Edge(code="E1-raw", name="Raw feed", source_node_id=src.id, target_node_id=sep.id)
        e2 = Edge(code="E2-skim", name="Skim to product", source_node_id=sep.id, target_node_id=sink.id)
        e3 = Edge(code="E3-cream", name="Cream to tank", source_node_id=sep.id, target_node_id=tank.id)
        e4 = Edge(code="E4-product", name="Cream product", source_node_id=tank.id, target_node_id=sink.id)
        e5 = Edge(code="E5-cross-out", name="Cream sent to later batch",
                  source_node_id=tank.id, target_node_id=later.id, cross_batch=True)
        e6 = Edge(code="E6-cross-back", name="Later batch return",
                  source_node_id=hold.id, target_node_id=tank.id, cross_batch=True)
        e7 = Edge(code="E7-later-transfer", name="Transfer in later batch",
                  source_node_id=later.id, target_node_id=hold.id, cross_batch=True)
        db.add_all([e1, e2, e3, e4, e5, e6, e7]); db.flush()

        ms = []
        def half(edge, q, fat=None, dry=False, solids=None):
            for i, (s, e) in enumerate(((T0, T1), (T1, T2))):
                ms.append(edge_measurement(seg_a, edge, "mass_flow", q, s, e, "kg/h",
                                           sigma=0.01, range_code=f"range-{'low' if i == 0 and edge.code == 'E5-cross-out' else 'high'}"))
                if fat is not None:
                    ms.append(edge_measurement(seg_a, edge, "fat_fraction", fat, s, None,
                                               "fraction", basis="dry" if dry else "wet", sigma=0.0001))
                    if dry and solids is not None:
                        ms.append(edge_measurement(seg_a, edge, "solids_fraction", solids, s, None,
                                                   "fraction", sigma=0.0001))
        half(e1, 1000.0, 0.048)
        # Skim has effectively zero fat in the hand calculation.
        half(e2, 900.0, 0.0)
        half(e3, 100.0, 0.48)
        half(e4, 60.0, 0.50)
        # Two adjacent meter ranges, each 0.5 h => 20 kg total.
        ms.append(edge_measurement(seg_a, e5, "mass_flow", 40.0, T0, T1, "kg/h",
                                   sigma=0.01, range_code="low"))
        ms.append(edge_measurement(seg_a, e5, "mass_flow", 0.0, T1, T2, "kg/h",
                                   sigma=0.01, range_code="high"))
        ms.append(edge_measurement(seg_a, e5, "fat_fraction", 0.40, T0, None,
                                   "fraction", sigma=0.0001))
        # e6 ownership is later segment but enters A's balance.
        for s, e in ((T0, T1), (T1, T2)):
            ms.append(edge_measurement(seg_b, e6, "mass_flow", 20.0, s, e, "kg/h", sigma=0.01))
            ms.append(edge_measurement(seg_b, e6, "fat_fraction", 0.40, s, None,
                                       "fraction", sigma=0.0001))
            ms.append(edge_measurement(seg_b, e7, "mass_flow", 20.0, s, e, "kg/h", sigma=0.01))
            ms.append(edge_measurement(seg_b, e7, "fat_fraction", 0.40, s, None,
                                       "fraction", sigma=0.0001))

        # Tank bottom old material: I + inputs = outputs + F.
        ms += [
            inventory_measurement(seg_a, tank, "mass", 100.0, T0, 0.01),
            inventory_measurement(seg_a, tank, "fat_mass", 50.0, T0, 0.005),
            inventory_measurement(seg_a, tank, "mass", 140.0, T2, 0.01),
            inventory_measurement(seg_a, tank, "fat_mass", 68.0, T2, 0.005),
        ]
        db.add_all(ms)
        batch_a.current_version = 1
        batch_b.current_version = 1
        seg_a.version = 1
        seg_b.version = 1
        db.commit()
        return "seeded B-DEMO-A/B-DEMO-B"
    finally:
        db.close()


if __name__ == "__main__":
    print(seed())
