"""Persist the Hugging Face user and workspace directory."""
from alembic import op
import sqlalchemy as sa

revision = "0003_hf_workspace_directory"
down_revision = "0002_persona_tenancy"
branch_labels = depends_on = None


def upgrade():
    op.create_table("users", sa.Column("user_id", sa.Text, primary_key=True), sa.Column("username", sa.Text), sa.Column("display_name", sa.Text), sa.Column("picture", sa.Text), sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("workspaces", sa.Column("workspace_id", sa.Text, primary_key=True), sa.Column("workspace_type", sa.Text, nullable=False), sa.Column("name", sa.Text, nullable=False), sa.Column("provider_ref", sa.Text, nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.add_column("workspace_memberships", sa.Column("source", sa.Text, nullable=False, server_default="legacy"))
    op.add_column("workspace_memberships", sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("workspace_memberships", "active")
    op.drop_column("workspace_memberships", "source")
    op.drop_table("workspaces")
    op.drop_table("users")
