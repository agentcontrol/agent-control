/**
 * Form values for the SQL evaluator.
 * Uses snake_case to match API field names directly.
 */
export interface SqlFormValues {
  // Multi-Statement
  allow_multi_statements: boolean;
  max_statements: number | "";
  // Operations
  blocked_operations: string; // Comma-separated (e.g., "DROP,DELETE,TRUNCATE")
  allowed_operations: string; // Comma-separated (e.g., "SELECT,INSERT,UPDATE")
  block_ddl: boolean;
  block_dcl: boolean;
  // Table/Schema Access
  allowed_tables: string; // Comma-separated
  blocked_tables: string; // Comma-separated
  allowed_schemas: string; // Comma-separated
  blocked_schemas: string; // Comma-separated
  // Column Presence
  required_columns: string; // Comma-separated
  column_presence_logic: "any" | "all";
  column_context: "select" | "where" | "";
  column_context_scope: "top_level" | "all";
  // Limits
  require_limit: boolean;
  max_limit: number | "";
  max_result_window: number | "";
  // Options
  case_sensitive: boolean;
  dialect: "postgres" | "mysql" | "tsql" | "oracle" | "sqlite";
  // Query Complexity Limits
  max_subquery_depth: number | "";
  max_joins: number | "";
  max_union_count: number | "";
}
