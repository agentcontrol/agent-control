# Management-vertical harness

A reproducible end-to-end check for the management-vertical authz flow.
Walks the happy path from the plan's §9 (list controls, read bindings,
attach, detach) plus three deny cases (cross-org, cross-project,
insufficient permissions).

Intended use: validate a locally-running stack of three services —
Agent Control, Galileo `api`, and Galileo `authz` — without needing a UI.

## What it exercises

- `GET  /api/v1/controls`
- `GET  /api/v1/targets/log_stream/{id}/controls`
- `PUT  /api/v1/targets/log_stream/{id}/controls/{control_id}`
- `DELETE /api/v1/targets/log_stream/{id}/controls/{control_id}`

Under the hood each request runs through Agent Control's pluggable auth
seam. In `http_upstream` mode AC calls
`api /internal/agent_control/auth/check_management_access`, which in
turn runs a Cerbos check. The harness asserts the observable HTTP
responses; it does not introspect Cerbos or api logs.

## Prerequisites

1. A local stack with `AGENT_CONTROL_MANAGEMENT_AUTH_MODE=http_upstream`
   and the upstream URL pointed at a running `api`.
2. A Galileo user with **owner** role on some project that contains a
   log-stream Run.
3. A control pre-seeded in the same org.

## Usage

```bash
export HARNESS_AC_URL=http://localhost:8000
export HARNESS_GALILEO_USER_TOKEN=<jwt-or-bearer-token>
export HARNESS_LOG_STREAM_ID=<uuid-of-a-run-with-task_type-log_stream>
export HARNESS_CONTROL_ID=<int-id-of-a-seeded-control>

# Optional (enables additional deny cases):
export HARNESS_CROSS_ORG_USER_TOKEN=...
export HARNESS_CROSS_PROJECT_USER_TOKEN=...
export HARNESS_VIEWER_TOKEN=...

uv run --package agent-control-server python tools/management_vertical_harness/harness.py
```

Exit code 0 on success, non-zero on first failed assertion. Output is
one line per check so failures are easy to pinpoint.

## Notes

- The harness detaches the control at the end of the happy path, so it
  leaves the system in the same state it found. Re-running is idempotent.
- If `HARNESS_CONTROL_ID` is already attached+enabled when the harness
  starts, the harness aborts. Detach it manually before re-running.
- Deny-case tokens are optional so the harness is useful even in a
  minimal single-user dev setup. In that mode only the happy path runs.
