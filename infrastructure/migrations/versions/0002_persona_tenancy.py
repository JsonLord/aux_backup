"""Add workspace attribution to persisted personas."""
from alembic import op
import sqlalchemy as sa

revision = "0002_persona_tenancy"
down_revision = "0001_control_plane"
branch_labels = depends_on = None


def upgrade():
    op.add_column("personas", sa.Column("workspace_id", sa.Text, nullable=False, server_default="local"))
    op.add_column("personas", sa.Column("owner_user_id", sa.Text, nullable=False, server_default="local"))
    op.create_index("ix_personas_workspace_created", "personas", ["workspace_id", "created_at"])


def downgrade():
    op.drop_index("ix_personas_workspace_created", table_name="personas")
    op.drop_column("personas", "owner_user_id")
    op.drop_column("personas", "workspace_id")
