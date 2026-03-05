# SQL Evaluator Quickstart Guide

A practical guide for configuring SQL validation controls in your AI agent.

---

## What is the SQL Evaluator?

The SQL Evaluator validates SQL query strings (e.g., from LLM responses) before they execute against your database. It acts as a security and safety layer, preventing dangerous operations, enforcing access rules, and ensuring data isolation.

**Technical Foundation**: Uses [sqlglot](https://github.com/tobymao/sqlglot) with the Rust-accelerated parser (`sqlglot[rs]`) for high-performance SQL parsing and AST-based validation.

> **💡 Performance Note**
>
> The Rust-accelerated parser provides significantly faster SQL parsing performance. However, it requires the Rust compiler to be installed on your system during installation. If Rust is not available, `sqlglot[rs]` automatically falls back to the slower Python-based parser—everything will still work correctly, just with reduced performance.
>
> **To install Rust**: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
> **To verify Rust tokenizer is active**: `python -c "import sqlglot_rs; print('✓ Rust tokenizer installed')"`

> **⚠️ Blocking Behavior & Performance**
>
> The `sqlglot.parse()` function is **synchronous** (no async version exists) and is **CPU-bound** (pure Python/Rust). Parsing happens inline during validation.
>
> **Official benchmark results** (Python 3.9.6):
> - **Short query**: ~0.4ms
> - **Long query**: ~5ms
> - **Complex query**: ~19ms
>
> **Why this is not a concern**:
> - Parsing overhead is negligible compared to database query execution time
> - sqlglot is the fastest pure-Python SQL parser available
> - Typical LLM-generated queries are straightforward and parse quickly
> - This runs as a pre-execution validation step where milliseconds don't matter
>
> **If you need true non-blocking behavior**: Wrap validation in `asyncio.to_thread()` or a thread pool executor, though this is rarely necessary for typical use cases.

> **⚠️ Important Security Note**
>
> This evaluator validates query structure and enforces access rules, but **it is not a complete defense against SQL injection**. The primary defense against SQL injection is using **prepared statements** (parameterized queries) at the database layer. This evaluator provides an additional security layer by validating query syntax and enforcing controls, but should not be relied upon as the sole protection mechanism.
>
> **Best Practice**: Always use prepared statements/parameterized queries when executing SQL from untrusted sources. This evaluator complements, but does not replace, proper database security practices.

**Key Benefits:**
- **Security**: Block dangerous operations (DROP, DELETE, TRUNCATE)
- **Safety**: Prevent accidental large data pulls with LIMIT controls
- **Multi-tenancy**: Enforce tenant isolation via required columns
- **Compliance**: Control access to sensitive tables and schemas
- **Performance**: Limit query complexity and result set sizes

**When to use:** Any application where SQL query strings from LLMs need validation before execution, especially in production with sensitive data or multi-tenant architectures.

**Common Use Cases:**
- **Multi-Tenant SaaS**: Ensure customers never access each other's data (require `tenant_id` filtering)
- **Customer Support Chatbots**: Read-only access to customer data, block modifications
- **Analytics/BI Agents**: Limit to reporting schemas, prevent production database access
- **Healthcare (HIPAA)**: Strict controls for patient data, require consent flags
- **Financial Services (SOX)**: Audit-ready controls for financial data
- **E-commerce Marketplaces**: Seller isolation, prevent cross-seller data access
- **Data Migration Tools**: Allow writes but block schema changes
- **Internal Admin Tools**: Elevated permissions with safety guardrails
- **Read-Only Reporting**: Prevent accidental data modification
- **Production Safety**: Block destructive operations (DROP, TRUNCATE, DELETE)

---

## Configuration Options

The SQL Evaluator validates queries in this order:

1. **Syntax** - SQL must be parseable (invalid SQL returns error, not block)
2. **Multi-Statement** - Control multi-statement queries
3. **Operations** - Block/allow SQL operations
4. **Table/Schema Access** - Restrict accessible tables/schemas
5. **Column Presence** - Require specific columns
6. **Limits** - Enforce LIMIT clauses and max values
7. **Query Complexity** - Limit subquery depth, JOINs, and set operations

> **Note**: When SQL cannot be parsed, the evaluator returns `matched=True` (validation fails). See [Error Handling Behavior](#error-handling-behavior) for details.

> **🔒 Security**: All checks recursively validate subqueries, CTEs, and nested SELECT statements to prevent security bypasses.

### 1. Multi-Statement

**What**: Control whether multiple SQL statements are allowed in a single query.

**When to use**:
- **Security**: Prevent SQL injection attacks like `"SELECT x; DROP TABLE y"`
- **Simplicity**: Enforce one operation per query for easier auditing

**Configuration**:
```json
{
  "allow_multi_statements": false
}
```

**Example**: Block all multi-statement queries:
```json
{
  "allow_multi_statements": false
}
```

**Example**: Allow up to 2 statements:
```json
{
  "max_statements": 2
}
```

---

### 2. Operations

**What**: Block or allow specific SQL operations (SELECT, INSERT, UPDATE, DELETE, DROP, etc.).

**When to use**:
- **Read-only agents**: Only allow SELECT
- **Data safety**: Block destructive operations (DROP, TRUNCATE, DELETE)
- **Controlled access**: Limit to specific operation types

**Configuration**:
```json
{
  "allowed_operations": ["SELECT"],           // Allowlist mode (only these)
  "blocked_operations": ["DROP", "DELETE"],   // Blocklist mode (block these)
  "block_ddl": true,                          // Block all DDL (CREATE, ALTER, DROP)
  "block_dcl": true                           // Block all DCL (GRANT, REVOKE)
}
```

> **Note**: When both `allowed_operations` and `blocked_operations` are configured (e.g., via `allowed_operations` + `block_ddl`), **BOTH checks are enforced**. An operation must pass both checks to be allowed. For most use cases, choose either allowlist (`allowed_operations`) or blocklist (`blocked_operations`) mode, not both.

**Example**: Read-only agent:
```json
{
  "allowed_operations": ["SELECT"]
}
```

**Example**: Block destructive operations:
```json
{
  "blocked_operations": ["DROP", "TRUNCATE", "DELETE"]
}
```

**Example**: Block utility operations for information disclosure prevention:
```json
{
  "blocked_operations": ["SHOW", "DESCRIBE", "ANALYZE", "SET", "USE", "COPY"]
}
```

> **💡 Complete List of Supported Operations**
>
> The evaluator recognizes and can control the following SQL operations:
>
> **DML (Data Manipulation)**:
> - `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`
>
> **DDL (Data Definition)** - blocked by `block_ddl=true`:
> - `CREATE`, `DROP`, `ALTER`, `TRUNCATE`, `COMMENT`
>
> **DCL (Data Control)** - blocked by `block_dcl=true`:
> - `GRANT`, `REVOKE`
>
> **TCL (Transaction Control)**:
> - `COMMIT`, `ROLLBACK`
>
> **Utility Commands**:
> - `SET`, `SHOW`, `USE`, `DESCRIBE`, `COPY`, `LOCK`, `ANALYZE`
>
> **Fallback**:
> - `COMMAND` - Unsupported SQL commands that sqlglot cannot parse into specific types
>
> Commands like `SHOW`, `DESCRIBE`, `ANALYZE`, `SET`, `USE`, and `COPY` can be blocked individually using `blocked_operations` to prevent schema inspection or information disclosure in restricted environments.
>
> **⚠️ Known Limitation**: The `EXPLAIN` command has limited support in sqlglot and may parse as a generic `COMMAND` type, making it difficult to block reliably. If you need to block `EXPLAIN`, consider using database-level permissions instead.

---

### 3. Table/Schema Access

**What**: Restrict which tables and schemas can be accessed.

**When to use**:
- **Multi-tenant isolation**: Only allow tenant-specific tables
- **Sensitive data protection**: Block access to admin/system tables
- **Dataset limitation**: Restrict to analytics or reporting tables only

**Configuration**:
```json
{
  "allowed_tables": ["users", "orders"],          // Only these tables
  "blocked_tables": ["sensitive_data"],           // Block these tables
  "allowed_schemas": ["public", "analytics"],     // Only these schemas
  "blocked_schemas": ["system", "admin"]          // Block these schemas
}
```

> **Note**: Use either `allowed_*` OR `blocked_*` for each type, not both.

**Example**: Restrict to specific tables:
```json
{
  "allowed_tables": ["users", "orders", "products"]
}
```

**Example**: Block sensitive schemas:
```json
{
  "blocked_schemas": ["admin", "system", "internal"]
}
```

> **💡 CTE (Common Table Expression) Handling**
>
> Tables defined as CTEs (WITH clauses) within a query are automatically excluded from table access checks. For example:
> ```sql
> WITH temp AS (SELECT * FROM orders)
> SELECT * FROM temp
> ```
> If you configure `allowed_tables: ["users"]`, this query will be **allowed** because `temp` is recognized as a CTE defined in the query itself, not an external table. Only the base table `orders` is validated against your table access rules.
>
> This behavior allows queries to use CTEs for intermediate results without restriction, while still enforcing access controls on the actual database tables being queried.

---

### 4. Column Presence

**What**: Require specific columns in queries (e.g., `tenant_id` in WHERE clause).

**When to use**:
- **Multi-tenant security**: Ensure tenant_id filtering to prevent data leakage
- **Compliance**: Enforce required audit columns
- **Data filtering**: Guarantee proper scoping in all queries

**Configuration**:
```json
{
  "required_columns": ["tenant_id"],
  "column_presence_logic": "any",        // "any" or "all"
  "column_context": "where",             // "where", "select", or null (anywhere)
  "column_context_scope": "top_level"    // "top_level" or "all" (default: "all")
}
```

**Example**: Require tenant_id in WHERE (strict RLS security):
```json
{
  "required_columns": ["tenant_id"],
  "column_context": "where",
  "column_context_scope": "top_level"    // Ensures tenant_id is in outer WHERE, not subquery
}
```

> **🔒 Multi-Tenant Security Best Practice**: Use `column_context_scope: "top_level"` to prevent subquery bypasses. This ensures `tenant_id` filtering is in the outer query, not just nested subqueries, preventing attackers from bypassing Row-Level Security (RLS) with queries like:
> ```sql
> -- ❌ Blocked with top_level: tenant_id only in subquery
> SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE tenant_id = 123)
>
> -- ✅ Allowed with top_level: tenant_id in outer WHERE
> SELECT * FROM users WHERE tenant_id = 123 AND id IN (SELECT user_id FROM orders)
> ```

**Example**: Require multiple audit columns anywhere:
```json
{
  "required_columns": ["created_by", "created_at"],
  "column_presence_logic": "all"
}
```

---

### 5. Limits

**What**: Require LIMIT clause on SELECT queries and enforce maximum LIMIT value and pagination depth.

**When to use**:
- **Performance protection**: Prevent accidentally pulling millions of rows
- **Cost control**: Limit data transfer and query costs
- **Agent safety**: Prevent AI from requesting too much data
- **Deep pagination attacks**: Prevent expensive OFFSET queries

**Configuration**:
```json
{
  "require_limit": true,      // Require LIMIT on all SELECT queries
  "max_limit": 1000,          // Maximum LIMIT value allowed
  "max_result_window": 10000  // Maximum LIMIT + OFFSET value
}
```

> **Note**: LIMIT checks only apply to SELECT queries. INSERT, UPDATE, DELETE are unaffected.

**Example**: Require LIMIT on all SELECTs:
```json
{
  "require_limit": true
}
```

**Example**: Limit to 1000 rows max:
```json
{
  "require_limit": true,
  "max_limit": 1000
}
```

**Example**: Prevent deep pagination attacks:
```json
{
  "max_result_window": 10000  // Allows "LIMIT 100 OFFSET 9900", blocks "LIMIT 10 OFFSET 10000"
}
```

> **💡 Deep Pagination Protection**: `max_result_window` limits the sum of LIMIT + OFFSET to prevent expensive queries. Similar to Elasticsearch's `index.max_result_window`, this stops attackers from using large OFFSET values like `LIMIT 10 OFFSET 1000000` which can cause severe database performance degradation.

> **⚠️ Indeterminate LIMIT Values**: The evaluator cannot determine LIMIT values for `LIMIT ALL`, `LIMIT (SELECT ...)`, or parameter placeholders (`LIMIT $1`, `LIMIT ?`). See the "Fail-Safe Behavior" section below for how these cases are handled.

---

### 6. Query Complexity

**What**: Limit query complexity to prevent Denial of Service (DoS) attacks.

**When to use**:
- **DoS protection**: Prevent computationally expensive queries
- **Performance control**: Limit resource-intensive operations
- **Cost management**: Prevent queries that consume excessive database resources

**Configuration**:
```json
{
  "max_subquery_depth": 5,    // Maximum nesting depth for subqueries
  "max_joins": 10,            // Maximum number of JOIN operations
  "max_union_count": 20       // Maximum number of UNION/INTERSECT/EXCEPT operations
}
```

**Example**: Prevent deeply nested queries:
```json
{
  "max_subquery_depth": 5  // Blocks SELECT FROM (SELECT FROM (SELECT FROM (...)))
}
```

**Example**: Limit JOIN complexity:
```json
{
  "max_joins": 10  // Prevents cartesian product attacks with too many joins
}
```

**Example**: Prevent UNION chains:
```json
{
  "max_union_count": 20  // Blocks massive UNION ALL chains
}
```

> **⚠️ DoS Protection**: These limits prevent attackers from crafting queries that consume excessive CPU, memory, or I/O resources. A single deeply nested query or query with many JOINs can bring down a database server.

---

## Common Scenarios

### Scenario 1: Read-Only Agent

Agent can only read data, with limits to prevent large pulls.

```json
{
  "allowed_operations": ["SELECT"],
  "require_limit": true,
  "max_limit": 1000
}
```

**Blocks**: INSERT, UPDATE, DELETE, DROP, queries without LIMIT, LIMIT > 1000
**Allows**: SELECT queries with LIMIT ≤ 1000

---

### Scenario 2: Multi-Tenant Security (Strict RLS)

Enforce tenant isolation and prevent cross-tenant data access with strict Row-Level Security (RLS).

```json
{
  "allowed_operations": ["SELECT", "INSERT", "UPDATE"],
  "required_columns": ["tenant_id"],
  "column_context": "where",
  "column_context_scope": "top_level",    // Prevent subquery RLS bypass
  "require_limit": true,
  "max_limit": 5000,
  "max_result_window": 50000
}
```

**Blocks**:
- Queries without `tenant_id` in outer WHERE clause
- Subquery RLS bypasses (tenant_id only in subquery)
- DELETE/DROP operations
- Deep pagination attacks

**Allows**: SELECT/INSERT/UPDATE with top-level tenant_id filtering and proper LIMITs

> **🔒 Why `column_context_scope: "top_level"`?** This prevents security bypasses where attackers place `tenant_id` in a subquery but access all tenant data in the outer query. Always use `"top_level"` for multi-tenant RLS enforcement.

---

### Scenario 3: Safe Data Analysis

Restrict to analytics tables only, prevent destructive operations.

```json
{
  "allowed_tables": ["analytics", "reports", "metrics"],
  "block_ddl": true,
  "allow_multi_statements": false,
  "max_limit": 10000
}
```

**Blocks**: DDL operations, multi-statements, non-analytics tables
**Allows**: Queries on analytics tables only

---

### Scenario 4: Production Safety

Comprehensive safety controls for production databases.

```json
{
  "blocked_operations": ["DROP", "TRUNCATE", "DELETE"],
  "blocked_schemas": ["system", "admin", "internal"],
  "allow_multi_statements": false,
  "require_limit": true,
  "max_limit": 1000
}
```

**Blocks**: Destructive operations, system schemas, multi-statements, large queries
**Allows**: Safe read/write operations only

---

## Configuration Reference

Quick reference of all configuration options:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| **Multi-Statement** ||||
| `allow_multi_statements` | bool | `true` | Allow multiple SQL statements in one query. Set to `false` to block `SELECT x; DROP TABLE y` |
| `max_statements` | int | `null` | Maximum number of statements allowed (e.g., `2` allows up to 2 statements) |
| **Operations** ||||
| `allowed_operations` | list[str] | `null` | Only allow these operations (e.g., `["SELECT"]` for read-only) |
| `blocked_operations` | list[str] | `null` | Block these operations (e.g., `["DROP", "DELETE", "TRUNCATE"]`) |
| `block_ddl` | bool | `false` | Block all DDL (CREATE, ALTER, DROP, etc.) |
| `block_dcl` | bool | `false` | Block all DCL (GRANT, REVOKE, etc.) |
| **Table/Schema Access** ||||
| `allowed_tables` | list[str] | `null` | Only allow these tables (e.g., `["users", "orders"]`) |
| `blocked_tables` | list[str] | `null` | Block these tables (e.g., `["sensitive_data"]`) |
| `allowed_schemas` | list[str] | `null` | Only allow these schemas (e.g., `["public", "analytics"]`) |
| `blocked_schemas` | list[str] | `null` | Block these schemas (e.g., `["system", "admin"]`) |
| **Column Presence** ||||
| `required_columns` | list[str] | `null` | Require these columns in queries (e.g., `["tenant_id"]` for multi-tenant) |
| `column_presence_logic` | `"any"` \| `"all"` | `"any"` | Require any column or all columns (e.g., `"all"` requires all specified columns) |
| `column_context` | `"select"` \| `"where"` \| `null` | `null` | Where columns must appear (e.g., `"where"` requires columns in WHERE clause) |
| `column_context_scope` | `"top_level"` \| `"all"` | `"all"` | Scope for column checks: `"top_level"` (outer query only, recommended for RLS) or `"all"` (all queries including subqueries) |
| **Limits** ||||
| `require_limit` | bool | `false` | Require LIMIT clause on all SELECT queries (recursively checks subqueries) |
| `max_limit` | int | `null` | Maximum LIMIT value allowed (e.g., `1000` prevents `LIMIT 10000`) |
| `max_result_window` | int | `null` | Maximum `LIMIT + OFFSET` value to prevent deep pagination (e.g., `10000`) |
| **Query Complexity** ||||
| `max_subquery_depth` | int | `null` | Maximum subquery nesting depth (e.g., `5` for typical apps, `null` = no limit) |
| `max_joins` | int | `null` | Maximum number of JOIN operations (e.g., `10-20` depending on use case) |
| `max_union_count` | int | `null` | Maximum number of UNION/INTERSECT/EXCEPT operations (e.g., `10-50`) |
| **Global Options** ||||
| `dialect` | `"postgres"` \| `"mysql"` \| `"tsql"` \| `"oracle"` \| `"sqlite"` | `"postgres"` | SQL dialect for parsing. Choose based on target database system. |
| `case_sensitive` | bool | `false` | Case-sensitive table/column matching (e.g., "Users" vs "users") |

---

## Error Handling Behavior

The evaluator handles edge cases as follows:

> **Note**: The `error` field is only set for evaluator errors (crashes, timeouts, missing dependencies), not for validation failures. Invalid SQL is a validation failure, not an evaluator error.

### Parse Failures

When SQL cannot be parsed (malformed SQL, unsupported syntax):
- Returns `matched=True` - invalid SQL fails validation
- No `error` field - this is a validation result, not an evaluator error
- The `message` field contains the parse error details

```sql
-- Example: Malformed SQL
SELCT * FORM users WERE id = 1
```
**Result**: `matched=True`, `confidence=1.0`, `message="SQL parsing failed: ..."`

### Indeterminate LIMIT Values

When LIMIT value cannot be determined (LIMIT ALL, NULL, parameters):
- The `max_limit` check is skipped
- `require_limit` still validates that a LIMIT clause is present

```sql
-- These are allowed (limit value check is skipped)
SELECT * FROM users LIMIT ALL
SELECT * FROM users LIMIT $1  -- Parameter placeholder
```

### Unknown Operations

When SQL parses but operation type cannot be determined:
- Returns `matched=True` (blocked)
- This prevents unknown/unsupported SQL from bypassing controls

---

## Validation Results

### Confidence Levels

The evaluator returns a `confidence` score with each validation result:

- **`confidence=1.0`**: Definite result
  - Used for all validation outcomes (pass or fail)
  - Examples: Blocked operation detected, parse failure, missing column, query passes all checks

### Query Metadata

When a query is blocked, the `EvaluatorResult.metadata` field contains diagnostic information:

**Always included**:
```json
{
  "query_snippet": "SELECT * FROM users...",  // Smart truncation (first 100 + last 100 chars)
  "query_length": 250,                        // Total query length in characters
  "query_hash": "a3f2c1b5d9e8f7a6"            // First 16 chars of SHA-256 hash
}
```

**Additional fields (violation-specific)**:
```json
{
  // Multi-statement violations
  "statement_count": 3,
  "max_statements": 2,

  // Operation violations
  "operations": ["SELECT", "DROP"],
  "blocked": ["DROP"],

  // Table violations
  "tables_accessed": [
    {"schema": "public", "table": "users"},
    {"schema": null, "table": "orders"}
  ],
  "violations": ["admin_table (table not allowed)"],

  // Column violations
  "required_columns": ["tenant_id"],
  "found_columns": ["user_id", "name"],
  "missing_columns": ["tenant_id"],
  "column_context": "where",

  // LIMIT violations
  "limit_value": 5000,
  "max_limit": 1000,
  "offset_value": 100,
  "result_window": 5100,
  "max_result_window": 10000,
  "violation": "missing_limit" | "missing_limit_in_subquery" | "indeterminate_limit",

  // Complexity violations
  "subquery_depth": 8,
  "max_subquery_depth": 5,
  "join_count": 15,
  "max_joins": 10,
  "union_count": 25,
  "max_union_count": 20
}
```

The `query_hash` field is useful for tracking blocked queries in logs without exposing sensitive SQL content. Smart truncation ensures long queries are still identifiable while keeping metadata size reasonable.

---

## Tips & Best Practices

✅ **Start permissive, tighten gradually**
Begin with broad access and narrow based on actual usage patterns. Monitor what queries your agent generates before adding restrictions.

✅ **Combine options for defense-in-depth**
Use multiple configuration options together (e.g., operation + table + limit controls) for comprehensive security.

✅ **Test configurations thoroughly**
Validate with representative queries before deploying to production. Ensure your agent can perform expected operations.

✅ **Monitor blocked queries**
Review what's being blocked to tune your rules. Too restrictive = agent can't work; too permissive = security gaps. Use the `query_hash` field from metadata to track queries without exposing SQL content in logs.

✅ **Check the error field for evaluator failures**
The `error` field is only set for evaluator errors (crashes, timeouts), not validation failures. If `error` is set, the evaluator couldn't complete evaluation.

✅ **Understand validation order**
Options are evaluated sequentially:
**Syntax → Multi-Statement → Operations → Tables → Columns → Limits → Complexity**

Earlier checks (like multi-statement) happen before later ones (like complexity). A query blocked by operations won't reach limit or complexity checks.

✅ **Invalid SQL is blocked**
Unparseable SQL returns `matched=True` - invalid SQL fails validation. This is a validation result, not an evaluator error.

✅ **Understand allow/block interaction**
- For tables/schemas: Use `allowed_*` **OR** `blocked_*`, not both (mutually exclusive)
- For operations: Both `allowed_operations` and `blocked_operations` can be enforced together (e.g., via `allowed_operations` + `block_ddl`), but for most use cases, choose one approach

---
