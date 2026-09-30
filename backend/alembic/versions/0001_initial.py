"""initial schema for batches, topology, measurements and reconciliation jobs"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("current_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "segments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Integer, sa.ForeignKey("batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="other"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("batch_id", "code", name="uq_segment_batch_code"),
    )
    op.create_index("ix_segments_batch_id", "segments", ["batch_id"])
    op.create_table(
        "nodes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("segment_id", sa.Integer, sa.ForeignKey("segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(32), nullable=False),
        sa.Column("include_inventory", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("segment_id", "code", name="uq_node_segment_code"),
    )
    op.create_index("ix_nodes_segment_id", "nodes", ["segment_id"])
    op.create_table(
        "edges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("source_node_id", sa.Integer, sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_node_id", sa.Integer, sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cross_batch", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "inventory_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("node_id", sa.Integer, sa.ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(32), nullable=False, server_default="kg"),
        sa.Column("uncertainty_type", sa.String(32), nullable=False, server_default="stddev"),
        sa.Column("uncertainty_value", sa.Float, nullable=False, server_default="0"),
        sa.UniqueConstraint("node_id", "as_of", name="uq_inventory_node_time"),
    )
    op.create_index("ix_inventory_node_time", "inventory_snapshots", ["node_id", "as_of"])
    op.create_table(
        "measurements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("segment_id", sa.Integer, sa.ForeignKey("segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("basis", sa.String(16), nullable=False, server_default="wet"),
        sa.Column("uncertainty_type", sa.String(32), nullable=False, server_default="stddev"),
        sa.Column("uncertainty_value", sa.Float, nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("range_code", sa.String(64), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.UniqueConstraint("segment_id", "target_type", "target_id", "metric", "period_start", "period_end",
                            name="uq_measurement_interval"),
    )
    op.create_index("ix_measurement_lookup", "measurements",
                    ["segment_id", "target_type", "target_id", "metric", "period_start", "period_end"])
    op.create_index("ix_measurements_observed", "measurements", ["observed_at"])
    op.create_table(
        "calc_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("version", sa.String(64), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("segment_id", sa.Integer, sa.ForeignKey("segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("input_version", sa.Integer, nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("input_summary", sa.String(128), nullable=False),
        sa.Column("input_snapshot", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(128), nullable=True),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "created_at"])
    op.create_table(
        "signoffs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("engineer", sa.String(128), nullable=False),
        sa.Column("input_summary", sa.String(128), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(128), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False, server_default="api"),
        sa.Column("detail", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_entity", "audit_events", ["entity_type", "entity_id"])


def downgrade() -> None:
    for name in reversed(["audit_events", "signoffs", "jobs", "calc_versions", "measurements",
                          "inventory_snapshots", "edges", "nodes", "segments", "batches"]):
        op.drop_table(name)
