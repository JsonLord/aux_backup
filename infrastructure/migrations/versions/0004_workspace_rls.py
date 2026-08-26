"""Add defense-in-depth PostgreSQL workspace row-level security."""
from alembic import op

revision = "0004_workspace_rls"
down_revision = "0003_hf_workspace_directory"
branch_labels = depends_on = None
TABLES = ("sessions", "jobs", "artifacts", "personas")


def upgrade():
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_workspace_isolation ON {table} USING (workspace_id = current_setting('app.workspace_id', true)) WITH CHECK (workspace_id = current_setting('app.workspace_id', true))")


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
