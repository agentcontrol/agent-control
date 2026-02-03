import {
  Box,
  Checkbox,
  Divider,
  NumberInput,
  Select,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";

import type { EvaluatorFormProps } from "../types";
import type { SqlFormValues } from "./types";

export const SqlForm = ({ form }: EvaluatorFormProps<SqlFormValues>) => {
  return (
    <Stack gap='md'>
      {/* SQL Dialect */}
      <Box>
        <Text size='sm' fw={500} mb={4}>
          SQL dialect
        </Text>
        <Select
          data={[
            { value: "postgres", label: "PostgreSQL" },
            { value: "mysql", label: "MySQL" },
            { value: "tsql", label: "T-SQL (SQL Server)" },
            { value: "oracle", label: "Oracle" },
            { value: "sqlite", label: "SQLite" },
          ]}
          size='sm'
          {...form.getInputProps("dialect")}
          onChange={(value) =>
            form.setFieldValue(
              "dialect",
              (value as SqlFormValues["dialect"]) || "postgres"
            )
          }
        />
        <Text size='xs' c='dimmed' mt={4}>
          SQL dialect for parsing (affects syntax interpretation)
        </Text>
      </Box>

      <Divider label='Multi-Statement Controls' labelPosition='left' />

      <Box>
        <Checkbox
          label='Allow multiple statements'
          size='sm'
          {...form.getInputProps("allow_multi_statements", {
            type: "checkbox",
          })}
          onChange={(event) => {
            form.setFieldValue("allow_multi_statements", event.target.checked);
            // Clear max_statements when disabling multi-statements
            if (!event.target.checked) {
              form.setFieldValue("max_statements", "");
            }
          }}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Allow queries like &quot;SELECT x; DROP TABLE y&quot;
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Max statements
        </Text>
        <NumberInput
          placeholder='Leave empty for no limit'
          min={1}
          max={100}
          disabled={!form.values.allow_multi_statements}
          {...form.getInputProps("max_statements")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Maximum statements allowed (only when multi-statements enabled)
        </Text>
      </Box>

      <Divider label='Operation Controls' labelPosition='left' />

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Blocked operations
        </Text>
        <TextInput
          placeholder='DROP, DELETE, TRUNCATE'
          disabled={!!form.values.allowed_operations}
          {...form.getInputProps("blocked_operations")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Comma-separated SQL operations to block (blocklist mode)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Allowed operations
        </Text>
        <TextInput
          placeholder='SELECT, INSERT, UPDATE'
          disabled={!!form.values.blocked_operations}
          {...form.getInputProps("allowed_operations")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Comma-separated SQL operations to allow (allowlist mode)
        </Text>
      </Box>

      <Box>
        <Checkbox
          label='Block DDL statements'
          size='sm'
          {...form.getInputProps("block_ddl", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Block CREATE, ALTER, DROP, TRUNCATE, RENAME, COMMENT
        </Text>
      </Box>

      <Box>
        <Checkbox
          label='Block DCL statements'
          size='sm'
          {...form.getInputProps("block_dcl", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Block GRANT, REVOKE statements
        </Text>
      </Box>

      <Divider label='Table/Schema Access' labelPosition='left' />

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Allowed tables
        </Text>
        <TextInput
          placeholder='users, orders, products'
          disabled={!!form.values.blocked_tables}
          {...form.getInputProps("allowed_tables")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Comma-separated tables to allow (allowlist mode)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Blocked tables
        </Text>
        <TextInput
          placeholder='admin_users, secrets'
          disabled={!!form.values.allowed_tables}
          {...form.getInputProps("blocked_tables")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Comma-separated tables to block (blocklist mode)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Allowed schemas
        </Text>
        <TextInput
          placeholder='public, analytics'
          disabled={!!form.values.blocked_schemas}
          {...form.getInputProps("allowed_schemas")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Comma-separated schemas to allow (allowlist mode)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Blocked schemas
        </Text>
        <TextInput
          placeholder='system, admin, internal'
          disabled={!!form.values.allowed_schemas}
          {...form.getInputProps("blocked_schemas")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Comma-separated schemas to block (blocklist mode)
        </Text>
      </Box>

      <Divider label='Column Presence Controls' labelPosition='left' />

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Required columns
        </Text>
        <TextInput
          placeholder='tenant_id, user_id'
          {...form.getInputProps("required_columns")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Columns that must be present (e.g., for multi-tenant security)
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Column presence logic
        </Text>
        <Select
          data={[
            { value: "any", label: "Any (at least one required column)" },
            { value: "all", label: "All (all required columns)" },
          ]}
          size='sm'
          {...form.getInputProps("column_presence_logic")}
          onChange={(value) =>
            form.setFieldValue(
              "column_presence_logic",
              (value as SqlFormValues["column_presence_logic"]) || "any"
            )
          }
        />
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Column context
        </Text>
        <Select
          data={[
            { value: "", label: "Anywhere in query" },
            { value: "where", label: "WHERE clause only" },
            { value: "select", label: "SELECT clause only" },
          ]}
          size='sm'
          clearable
          {...form.getInputProps("column_context")}
          onChange={(value) =>
            form.setFieldValue(
              "column_context",
              (value as SqlFormValues["column_context"]) || ""
            )
          }
        />
        <Text size='xs' c='dimmed' mt={4}>
          Where required columns must appear
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Column context scope
        </Text>
        <Select
          data={[
            { value: "all", label: "All (including subqueries)" },
            {
              value: "top_level",
              label: "Top level only (recommended for RLS)",
            },
          ]}
          size='sm'
          {...form.getInputProps("column_context_scope")}
          onChange={(value) =>
            form.setFieldValue(
              "column_context_scope",
              (value as SqlFormValues["column_context_scope"]) || "all"
            )
          }
        />
        <Text size='xs' c='dimmed' mt={4}>
          Whether to check only top-level or all clauses
        </Text>
      </Box>

      <Divider label='Limit Controls' labelPosition='left' />

      <Box>
        <Checkbox
          label='Require LIMIT clause'
          size='sm'
          {...form.getInputProps("require_limit", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Require SELECT queries to have a LIMIT clause
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Max LIMIT value
        </Text>
        <NumberInput
          placeholder='1000'
          min={1}
          {...form.getInputProps("max_limit")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Maximum allowed LIMIT value
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Max result window (LIMIT + OFFSET)
        </Text>
        <NumberInput
          placeholder='10000'
          min={1}
          {...form.getInputProps("max_result_window")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Maximum value of (LIMIT + OFFSET) for pagination control
        </Text>
      </Box>

      <Divider label='Query Complexity Limits' labelPosition='left' />

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Max subquery depth
        </Text>
        <NumberInput
          placeholder='5'
          min={1}
          max={100}
          {...form.getInputProps("max_subquery_depth")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Maximum nesting depth for subqueries
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Max JOINs
        </Text>
        <NumberInput
          placeholder='10'
          min={1}
          max={100}
          {...form.getInputProps("max_joins")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Maximum number of JOIN operations
        </Text>
      </Box>

      <Box>
        <Text size='sm' fw={500} mb={4}>
          Max UNION/INTERSECT/EXCEPT
        </Text>
        <NumberInput
          placeholder='10'
          min={1}
          max={100}
          {...form.getInputProps("max_union_count")}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Maximum number of set operations
        </Text>
      </Box>

      <Divider label='Options' labelPosition='left' />

      <Box>
        <Checkbox
          label='Case sensitive'
          size='sm'
          {...form.getInputProps("case_sensitive", { type: "checkbox" })}
        />
        <Text size='xs' c='dimmed' mt={4}>
          Case-sensitive table, column, and schema matching
        </Text>
      </Box>
    </Stack>
  );
};
