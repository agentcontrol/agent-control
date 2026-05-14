# Server Auth Contract

Agent Control keeps authentication and authorization provider-neutral. The server asks a configured provider whether a request may perform an operation, then scopes all data access with the returned `Principal`.

## Operations

Operations are stable strings. Deployers map them to their own permission model.

```text
controls.read
controls.create
controls.update
controls.delete
policies.read
policies.create
policies.update
agents.read
agents.create
agents.update
evaluators.read
observability.read
observability.write
control_bindings.read
control_bindings.write
runtime.token_exchange
runtime.use
```

## Principal

Providers return a generic principal. Agent Control treats `namespace_key`, `caller_id`, `target_type`, and `target_id` as opaque strings.

```json
{
  "namespace_key": "tenant-a",
  "is_admin": false,
  "caller_id": "user-or-key-id",
  "target_type": "session",
  "target_id": "target-123",
  "scopes": ["runtime.use"],
  "expires_at": "2026-05-11T15:00:00Z"
}
```

`namespace_key` is the tenancy boundary. Server queries filter by it, and namespace-aware foreign keys prevent cross-namespace references.

## Auth Modes

Management auth is selected by `AGENT_CONTROL_AUTH_MODE`.

| Mode | Meaning |
| --- | --- |
| `none` | No credentials required. Intended for local development only. |
| `api_key` | Validate caller credentials locally with `AGENT_CONTROL_API_KEYS` and/or `AGENT_CONTROL_ADMIN_API_KEYS`. Requires `AGENT_CONTROL_API_KEY_ENABLED=true`. `header` is accepted as a backwards-compatible alias. |
| `http_upstream` | POST each management authorization decision to `AGENT_CONTROL_AUTH_UPSTREAM_URL`. |

When `AGENT_CONTROL_AUTH_MODE` is unset, startup selects `api_key` if local API-key validation is enabled and `none` otherwise.

Runtime auth is selected by `AGENT_CONTROL_RUNTIME_AUTH_MODE`.

| Mode | Meaning |
| --- | --- |
| unset | Use `jwt` when `AGENT_CONTROL_RUNTIME_TOKEN_SECRET` is set. Otherwise runtime requests fall through to management auth. |
| `none` | No runtime credentials required. Intended for local development only. |
| `api_key` | Validate runtime requests with the same local API-key mechanism. |
| `jwt` | Require target-bound runtime tokens minted by `/api/v1/auth/runtime-token-exchange`. |

Common combinations:

| Management | Runtime | Use case |
| --- | --- | --- |
| `api_key` | unset | Existing standalone deployments. |
| `api_key` | `jwt` | Local management keys with short-lived target-bound runtime tokens. This does not perform per-target authorization; any valid local API key can exchange for any target in the local namespace. |
| `http_upstream` | `jwt` | External identity or authorization service for management, local token verify for high-volume runtime calls. |
| `none` | `none` | Single-process local development. Do not use in production. |

## HTTP Upstream Contract

When `AGENT_CONTROL_AUTH_MODE=http_upstream`, the server sends:

```http
POST {AGENT_CONTROL_AUTH_UPSTREAM_URL}
```

```json
{
  "operation": "control_bindings.write",
  "context": {
    "target_type": "session",
    "target_id": "target-123"
  }
}
```

The provider forwards inbound `X-API-Key`, `Authorization`, and `Cookie` headers. Add deployer-specific header names with `AGENT_CONTROL_AUTH_UPSTREAM_EXTRA_FORWARD_HEADERS`, for example:

```text
AGENT_CONTROL_AUTH_UPSTREAM_EXTRA_FORWARD_HEADERS=Vendor-API-Key,X-Workspace-Id
```

If `AGENT_CONTROL_AUTH_UPSTREAM_SERVICE_TOKEN` is set, it is forwarded on `AGENT_CONTROL_AUTH_UPSTREAM_SERVICE_TOKEN_HEADER` or `X-Agent-Control-Service-Token` by default.

A successful upstream response is:

```json
{
  "namespace_key": "tenant-a",
  "is_admin": false,
  "caller_id": "user-or-key-id",
  "target_type": "session",
  "target_id": "target-123",
  "scopes": ["runtime.use"],
  "expires_at": "2026-05-11T15:00:00Z"
}
```

Only `namespace_key` is always required. `target_type` and `target_id` must be returned together when present. `expires_at` must include timezone information.

Status handling:

| Upstream status | Agent Control result |
| --- | --- |
| `200` | Parse the principal grant. |
| `401` | Authentication error. |
| `403` | Forbidden error. |
| `404` | Not found error. |
| `429` | `503` with a rate-limit detail and `Retry-After` hint when present. |
| Other statuses or upstream network errors | Fail closed with `503`. |
| Malformed `200` principal response | Fail closed with `502`. |
| `200` target grant that conflicts with request context | Fail closed with `403`. |

## Runtime JWT Claims

`/api/v1/auth/runtime-token-exchange` is a management-style request. The configured management provider authorizes `runtime.token_exchange` for the requested target. Agent Control then mints its own HS256 JWT with `AGENT_CONTROL_RUNTIME_TOKEN_SECRET`.

The token payload contains:

```json
{
  "iss": "agent-control/server",
  "domain": "runtime",
  "namespace_key": "tenant-a",
  "actor_id": "user-or-key-id",
  "target_type": "session",
  "target_id": "target-123",
  "scopes": ["runtime.use"],
  "iat": 1778509800,
  "exp": 1778510100,
  "jti": "opaque-token-id"
}
```

Verification requires the expected issuer, `domain="runtime"`, a valid signature, an unexpired `exp`, and `runtime.use` in `scopes`. The token is accepted only for requests whose `target_type` and `target_id` match the bound target.

The expiry is the earlier of `AGENT_CONTROL_RUNTIME_TOKEN_TTL_SECONDS` and the upstream grant's `expires_at` when supplied. Runtime token TTLs are capped at 86400 seconds.
