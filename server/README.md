# Agent Control Server

FastAPI server that powers Agent Control. It manages agents and controls, evaluates requests at runtime, and exposes REST APIs used by the SDKs and UI.

## What it provides

- Agent registration and control association
- Control CRUD and evaluator configuration
- Runtime evaluation (`/api/v1/evaluation`) with pre/post stages
- Observability endpoints for events and stats
- API key authentication for production deployments

## Quick start (local)

From the repo root:

```bash
make sync
make server-run
```

Server runs on http://localhost:8000. The UI expects this base URL by default.

To use non-default local ports with `make server-run`, export
`AGENT_CONTROL_PORT` for the server listen port. If you also want the local
Postgres container exposed on a different host port, set
`AGENT_CONTROL_DB_HOST_PORT` and point the server at the same value with
`AGENT_CONTROL_DB_PORT`.

## Database migrations

The server package includes the `agent-control-migrate` command for bundled
Alembic migrations.

In production, migrations are serialized with a Postgres advisory lock. Alembic
runs each migration revision in its own transaction, so if an upgrade across
multiple revisions fails, earlier revisions may already be committed. Check the
current revision before retrying:

```bash
agent-control-migrate current
agent-control-migrate upgrade head
```

## PostgreSQL driver runtime

`agent-control-server` depends on plain `psycopg`. The published Docker image
installs Debian `libpq5` and sets `PSYCOPG_IMPL=python` so the server uses
psycopg's Python implementation with the OS libpq library.

For wheel-based deployments outside Docker, either install the OS libpq runtime
package for your platform, or install `agent-control-server[binary]` if you want
psycopg's bundled binary package.

## Configuration

Server configuration is driven by environment variables (database, auth, observability, evaluators). For the full list and examples, see the docs.

Full guide: https://docs.agentcontrol.dev/components/server

## Project-owned control definitions

Organization definitions keep `owner_project_id=null`. Existing definitions are
not reassigned from their bindings or clone lineage. Ordinary `controls.*`
authorization remains the organization contract.

An ownership-aware HTTP upstream can authorize `project_controls.create`,
`project_controls.read`, `project_controls.update`, and `project_controls.delete`
with `{ "project_id": "<project ID>" }`. Its response must contain the matching
typed `project_id` and the authenticated organization `namespace_key`. Configure
the identity-resolution URL so direct-ID and version-history routes can resolve
the stored owner before requesting its grant. Standalone providers without this
capability reject project ownership; they retain existing organization behavior.

Create and clone-and-bind accept optional `owner_project_id`. The clone source
requires its own read grant. The destination create grant and stream-binding grant
must identify the same project. An already project-owned source cannot be cloned
into organization scope or another project. Clone IDs and configurations remain
independent; deleting a source does not recursively delete its clones.

`GET /api/v1/controls` returns organization definitions by default. Supplying
`owner_project_id` returns that project's definitions, including detached copies,
under project-read authorization. Ownership filtering applies before pagination
and totals. A stream-filtered list includes that stream's authorized project
definitions and, when the caller also has the existing organization read grant,
its legacy organization definitions. It never selects another project's copies.
Remove deletes one binding, not its definition or ownership. Reattach the retained
ID with `PUT /api/v1/control-bindings/by-key`, not clone-and-bind. Project-owned
definitions cannot enter organization-level agent/policy associations.

Lifecycle cleanup is a separate permission: `project_controls.cleanup` requires
upstream project-deletion authority, and `control_bindings.cleanup` requires
stream-deletion authority. Neither is interchangeable with definition Delete or
binding Write. Project and target lifecycle row locks serialize cleanup with new
definition/attachment writes. Committed deletion tombstones reject later writes;
cleanup retries are idempotent. Cleanup removes only the selected project's owned
definitions and approved stream bindings, not organization sources or another
project's definitions.

Deploy compatible upstream operations, typed grants, project policy, and identity
resolution to every API instance before enabling ownership-aware clients or
deletion integration. Do not activate these features against an older upstream.
The additive migration leaves legacy data organization-owned; migration of legacy
shared/detached records requires an explicit plan. Downgrade refuses to erase a
non-null owner, including owners of soft-deleted definitions.

After project-owned data exists, do not roll back to an older server binary:
older list/read handlers ignore ownership and could expose those definitions in
the organization collection even if the new database column remains. To pause
activation, disable project-owned creation in the ownership-aware clients/upstream
and keep the new server running. A binary rollback requires a reviewed isolation
backport or data migration; the Alembic downgrade guard alone does not protect it.
