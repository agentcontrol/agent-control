import {
  Checkbox,
  Divider,
  NumberInput,
  Select,
  Stack,
  TextInput,
} from "@mantine/core";

import {
  labelPropsInline,
  LabelWithTooltip,
} from "@/core/components/label-with-tooltip";

import type { EvaluatorFormProps } from "../types";
import type { SqlFormValues } from "./types";

export const SqlForm = ({ form }: EvaluatorFormProps<SqlFormValues>) => {
  return (
    <Stack gap="md">
      <Select
        label={
          <LabelWithTooltip
            label="SQL dialect"
            tooltip="SQL dialect for parsing (affects syntax interpretation)"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "postgres", label: "PostgreSQL" },
          { value: "mysql", label: "MySQL" },
          { value: "tsql", label: "T-SQL (SQL Server)" },
          { value: "oracle", label: "Oracle" },
          { value: "sqlite", label: "SQLite" },
        ]}
        size="sm"
        {...form.getInputProps("dialect")}
        onChange={(value) =>
          form.setFieldValue(
            "dialect",
            (value as SqlFormValues["dialect"]) || "postgres"
          )
        }
      />

      <Divider label="Multi-Statement Controls" labelPosition="left" />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Allow multiple statements"
            tooltip='Allow queries like "SELECT x; DROP TABLE y"'
          />
        }
        size="sm"
        {...form.getInputProps("allow_multi_statements", {
          type: "checkbox",
        })}
        onChange={(event) => {
          form.setFieldValue("allow_multi_statements", event.target.checked);
          if (!event.target.checked) {
            form.setFieldValue("max_statements", "");
          }
        }}
      />

      <NumberInput
        label={
          <LabelWithTooltip
            label="Max statements"
            tooltip="Maximum statements allowed (only when multi-statements enabled)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="Leave empty for no limit"
        min={1}
        max={100}
        size="sm"
        disabled={!form.values.allow_multi_statements}
        {...form.getInputProps("max_statements")}
      />

      <Divider label="Operation Controls" labelPosition="left" />

      <TextInput
        label={
          <LabelWithTooltip
            label="Blocked operations"
            tooltip="Comma-separated SQL operations to block (blocklist mode)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="DROP, DELETE, TRUNCATE"
        size="sm"
        disabled={!!form.values.allowed_operations}
        {...form.getInputProps("blocked_operations")}
      />

      <TextInput
        label={
          <LabelWithTooltip
            label="Allowed operations"
            tooltip="Comma-separated SQL operations to allow (allowlist mode)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="SELECT, INSERT, UPDATE"
        size="sm"
        disabled={!!form.values.blocked_operations}
        {...form.getInputProps("allowed_operations")}
      />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Block DDL statements"
            tooltip="Block CREATE, ALTER, DROP, TRUNCATE, RENAME, COMMENT"
          />
        }
        size="sm"
        {...form.getInputProps("block_ddl", { type: "checkbox" })}
      />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Block DCL statements"
            tooltip="Block GRANT, REVOKE statements"
          />
        }
        size="sm"
        {...form.getInputProps("block_dcl", { type: "checkbox" })}
      />

      <Divider label="Table/Schema Access" labelPosition="left" />

      <TextInput
        label={
          <LabelWithTooltip
            label="Allowed tables"
            tooltip="Comma-separated tables to allow (allowlist mode)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="users, orders, products"
        size="sm"
        disabled={!!form.values.blocked_tables}
        {...form.getInputProps("allowed_tables")}
      />

      <TextInput
        label={
          <LabelWithTooltip
            label="Blocked tables"
            tooltip="Comma-separated tables to block (blocklist mode)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="admin_users, secrets"
        size="sm"
        disabled={!!form.values.allowed_tables}
        {...form.getInputProps("blocked_tables")}
      />

      <TextInput
        label={
          <LabelWithTooltip
            label="Allowed schemas"
            tooltip="Comma-separated schemas to allow (allowlist mode)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="public, analytics"
        size="sm"
        disabled={!!form.values.blocked_schemas}
        {...form.getInputProps("allowed_schemas")}
      />

      <TextInput
        label={
          <LabelWithTooltip
            label="Blocked schemas"
            tooltip="Comma-separated schemas to block (blocklist mode)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="system, admin, internal"
        size="sm"
        disabled={!!form.values.allowed_schemas}
        {...form.getInputProps("blocked_schemas")}
      />

      <Divider label="Column Presence Controls" labelPosition="left" />

      <TextInput
        label={
          <LabelWithTooltip
            label="Required columns"
            tooltip="Columns that must be present (e.g., for multi-tenant security)"
          />
        }
        labelProps={labelPropsInline}
        placeholder="tenant_id, user_id"
        size="sm"
        {...form.getInputProps("required_columns")}
      />

      <Select
        label={
          <LabelWithTooltip
            label="Column presence logic"
            tooltip="How to combine required columns (any vs all)"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "any", label: "Any (at least one required column)" },
          { value: "all", label: "All (all required columns)" },
        ]}
        size="sm"
        {...form.getInputProps("column_presence_logic")}
        onChange={(value) =>
          form.setFieldValue(
            "column_presence_logic",
            (value as SqlFormValues["column_presence_logic"]) || "any"
          )
        }
      />

      <Select
        label={
          <LabelWithTooltip
            label="Column context"
            tooltip="Where required columns must appear"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "", label: "Anywhere in query" },
          { value: "where", label: "WHERE clause only" },
          { value: "select", label: "SELECT clause only" },
        ]}
        size="sm"
        clearable
        {...form.getInputProps("column_context")}
        onChange={(value) =>
          form.setFieldValue(
            "column_context",
            (value as SqlFormValues["column_context"]) || ""
          )
        }
      />

      <Select
        label={
          <LabelWithTooltip
            label="Column context scope"
            tooltip="Whether to check only top-level or all clauses"
          />
        }
        labelProps={labelPropsInline}
        data={[
          { value: "all", label: "All (including subqueries)" },
          {
            value: "top_level",
            label: "Top level only (recommended for RLS)",
          },
        ]}
        size="sm"
        {...form.getInputProps("column_context_scope")}
        onChange={(value) =>
          form.setFieldValue(
            "column_context_scope",
            (value as SqlFormValues["column_context_scope"]) || "all"
          )
        }
      />

      <Divider label="Limit Controls" labelPosition="left" />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Require LIMIT clause"
            tooltip="Require SELECT queries to have a LIMIT clause"
          />
        }
        size="sm"
        {...form.getInputProps("require_limit", { type: "checkbox" })}
      />

      <NumberInput
        label={
          <LabelWithTooltip
            label="Max LIMIT value"
            tooltip="Maximum allowed LIMIT value"
          />
        }
        labelProps={labelPropsInline}
        placeholder="1000"
        min={1}
        size="sm"
        {...form.getInputProps("max_limit")}
      />

      <NumberInput
        label={
          <LabelWithTooltip
            label="Max result window (LIMIT + OFFSET)"
            tooltip="Maximum value of (LIMIT + OFFSET) for pagination control"
          />
        }
        labelProps={labelPropsInline}
        placeholder="10000"
        min={1}
        size="sm"
        {...form.getInputProps("max_result_window")}
      />

      <Divider label="Query Complexity Limits" labelPosition="left" />

      <NumberInput
        label={
          <LabelWithTooltip
            label="Max subquery depth"
            tooltip="Maximum nesting depth for subqueries"
          />
        }
        labelProps={labelPropsInline}
        placeholder="5"
        min={1}
        max={100}
        size="sm"
        {...form.getInputProps("max_subquery_depth")}
      />

      <NumberInput
        label={
          <LabelWithTooltip
            label="Max JOINs"
            tooltip="Maximum number of JOIN operations"
          />
        }
        labelProps={labelPropsInline}
        placeholder="10"
        min={1}
        max={100}
        size="sm"
        {...form.getInputProps("max_joins")}
      />

      <NumberInput
        label={
          <LabelWithTooltip
            label="Max UNION/INTERSECT/EXCEPT"
            tooltip="Maximum number of set operations"
          />
        }
        labelProps={labelPropsInline}
        placeholder="10"
        min={1}
        max={100}
        size="sm"
        {...form.getInputProps("max_union_count")}
      />

      <Divider label="Options" labelPosition="left" />

      <Checkbox
        label={
          <LabelWithTooltip
            label="Case sensitive"
            tooltip="Case-sensitive table, column, and schema matching"
          />
        }
        size="sm"
        {...form.getInputProps("case_sensitive", { type: "checkbox" })}
      />
    </Stack>
  );
};
