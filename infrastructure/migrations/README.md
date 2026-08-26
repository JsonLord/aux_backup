# Migrations

Alembic owns the production PostgreSQL schema. Run `alembic upgrade head` with
`DATABASE_URL` set to a PostgreSQL/psycopg URL. Migration `0001_control_plane`
creates tenant-attributed sessions, jobs, ordered events, attempts, artifact metadata,
workspace memberships, service credentials, and durable persona profiles. `create_store()` selects
`PostgresStore` for PostgreSQL URLs. Compose applies the migration before API startup;
the production-stack acceptance command is documented in `docs/stage-1-audit.md`.
