"""Initial tenant-attributed PostgreSQL control-plane schema."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_control_plane"
down_revision = branch_labels = depends_on = None
JSON = postgresql.JSONB


def upgrade():
    op.create_table("sessions", sa.Column("session_id", sa.Text, primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("metadata", JSON, nullable=False), sa.Column("external_ref", JSON, nullable=False), sa.Column("workspace_id", sa.Text, nullable=False), sa.Column("owner_user_id", sa.Text, nullable=False))
    op.create_index("ix_sessions_workspace_created", "sessions", ["workspace_id", "created_at"])
    op.create_table("jobs", sa.Column("job_id", sa.Text, primary_key=True), sa.Column("session_id", sa.Text, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("pipeline_run_id", sa.Text), sa.Column("type", sa.Text, nullable=False), sa.Column("version", sa.Text, nullable=False), sa.Column("status", sa.Text, nullable=False), sa.Column("depends_on", JSON, nullable=False), sa.Column("input_artifacts", JSON, nullable=False), sa.Column("output_artifacts", JSON, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("attempt", sa.Integer, nullable=False), sa.Column("seed", sa.BigInteger), sa.Column("metadata", JSON, nullable=False), sa.Column("error", JSON), sa.Column("idempotency_key", sa.Text), sa.Column("workspace_id", sa.Text, nullable=False), sa.Column("owner_user_id", sa.Text, nullable=False), sa.UniqueConstraint("workspace_id", "idempotency_key", name="uq_jobs_workspace_idempotency"))
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])
    op.create_table("events", sa.Column("job_id", sa.Text, sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True), sa.Column("sequence", sa.BigInteger, primary_key=True), sa.Column("type", sa.Text, nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("progress", sa.Float), sa.Column("data", JSON, nullable=False))
    op.create_table("attempts", sa.Column("job_id", sa.Text, sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True), sa.Column("attempt", sa.Integer, primary_key=True), sa.Column("status", sa.Text, nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("error", JSON))
    op.create_table("artifacts", sa.Column("artifact_id", sa.Text, primary_key=True), sa.Column("session_id", sa.Text, sa.ForeignKey("sessions.session_id", ondelete="CASCADE"), nullable=False), sa.Column("kind", sa.Text, nullable=False), sa.Column("content_type", sa.Text, nullable=False), sa.Column("path", sa.Text, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("metadata", JSON, nullable=False), sa.Column("workspace_id", sa.Text, nullable=False), sa.Column("owner_user_id", sa.Text, nullable=False), sa.Column("retention_class", sa.Text, nullable=False), sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.false()), sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.create_index("ix_artifacts_retention", "artifacts", ["pinned", "expires_at"])
    op.create_table("workspace_memberships", sa.Column("workspace_id", sa.Text, primary_key=True), sa.Column("user_id", sa.Text, primary_key=True), sa.Column("role", sa.Text, nullable=False), sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("service_credentials", sa.Column("credential_id", sa.Text, primary_key=True), sa.Column("name", sa.Text, nullable=False), sa.Column("secret_hash", sa.LargeBinary, nullable=False), sa.Column("salt", sa.LargeBinary, nullable=False), sa.Column("workspace_ids", postgresql.ARRAY(sa.Text), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)))
    op.create_table("personas", sa.Column("persona_id", sa.Text, primary_key=True), sa.Column("profile", JSON, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for table in ("personas", "service_credentials", "workspace_memberships", "artifacts", "attempts", "events", "jobs"):
        op.drop_table(table)
    op.drop_index("ix_sessions_workspace_created", table_name="sessions")
    op.drop_table("sessions")
