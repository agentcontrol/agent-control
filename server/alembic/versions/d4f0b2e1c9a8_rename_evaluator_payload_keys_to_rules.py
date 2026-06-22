"""rename evaluator payload keys to rules

Revision ID: d4f0b2e1c9a8
Revises: e2b7f4a9c6d1
Create Date: 2026-06-22 13:45:00.000000

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "d4f0b2e1c9a8"
down_revision = "e2b7f4a9c6d1"
branch_labels = None
depends_on = None


_HELPER_FUNCTIONS = """
CREATE OR REPLACE FUNCTION _ac_rename_object_key(
    input_value jsonb,
    old_key text,
    new_key text
) RETURNS jsonb AS $$
BEGIN
    IF (
        input_value IS NULL
        OR jsonb_typeof(input_value) <> 'object'
        OR NOT input_value ? old_key
    ) THEN
        RETURN input_value;
    END IF;

    IF input_value ? new_key THEN
        RETURN input_value - old_key;
    END IF;

    RETURN (input_value - old_key) || jsonb_build_object(new_key, input_value->old_key);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _ac_rename_condition_node(
    input_value jsonb,
    old_key text,
    new_key text
) RETURNS jsonb AS $$
DECLARE
    result jsonb;
    rewritten_children jsonb;
BEGIN
    IF input_value IS NULL OR jsonb_typeof(input_value) <> 'object' THEN
        RETURN input_value;
    END IF;

    result := _ac_rename_object_key(input_value, old_key, new_key);

    IF jsonb_typeof(result->'and') = 'array' THEN
        SELECT COALESCE(
            jsonb_agg(_ac_rename_condition_node(child.value, old_key, new_key)),
            '[]'::jsonb
        )
        INTO rewritten_children
        FROM jsonb_array_elements(result->'and') AS child(value);
        result := jsonb_set(result, '{and}', rewritten_children, false);
    END IF;

    IF jsonb_typeof(result->'or') = 'array' THEN
        SELECT COALESCE(
            jsonb_agg(_ac_rename_condition_node(child.value, old_key, new_key)),
            '[]'::jsonb
        )
        INTO rewritten_children
        FROM jsonb_array_elements(result->'or') AS child(value);
        result := jsonb_set(result, '{or}', rewritten_children, false);
    END IF;

    IF jsonb_typeof(result->'not') = 'object' THEN
        result := jsonb_set(
            result,
            '{not}',
            _ac_rename_condition_node(result->'not', old_key, new_key),
            false
        );
    END IF;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _ac_rename_control_data(
    input_value jsonb,
    old_key text,
    new_key text
) RETURNS jsonb AS $$
DECLARE
    result jsonb;
    template_value jsonb;
BEGIN
    IF input_value IS NULL OR jsonb_typeof(input_value) <> 'object' THEN
        RETURN input_value;
    END IF;

    -- Legacy flat controls used top-level selector + evaluator/rule.
    result := _ac_rename_object_key(input_value, old_key, new_key);

    IF jsonb_typeof(result->'condition') = 'object' THEN
        result := jsonb_set(
            result,
            '{condition}',
            _ac_rename_condition_node(result->'condition', old_key, new_key),
            false
        );
    END IF;

    IF (
        jsonb_typeof(result->'template') = 'object'
        AND result->'template' ? 'definition_template'
    ) THEN
        template_value := jsonb_set(
            result->'template',
            '{definition_template}',
            _ac_rename_control_data(
                result->'template'->'definition_template',
                old_key,
                new_key
            ),
            false
        );
        result := jsonb_set(result, '{template}', template_value, false);
    END IF;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _ac_rename_condition_trace(
    input_value jsonb,
    old_key text,
    new_key text
) RETURNS jsonb AS $$
DECLARE
    result jsonb;
    rewritten_children jsonb;
BEGIN
    IF input_value IS NULL OR jsonb_typeof(input_value) <> 'object' THEN
        RETURN input_value;
    END IF;

    result := _ac_rename_object_key(input_value, old_key, new_key);

    IF jsonb_typeof(result->'children') = 'array' THEN
        SELECT COALESCE(
            jsonb_agg(_ac_rename_condition_trace(child.value, old_key, new_key)),
            '[]'::jsonb
        )
        INTO rewritten_children
        FROM jsonb_array_elements(result->'children') AS child(value);
        result := jsonb_set(result, '{children}', rewritten_children, false);
    END IF;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _ac_rename_event_data(
    input_value jsonb,
    old_rule_name_key text,
    new_rule_name_key text,
    old_primary_key text,
    new_primary_key text,
    old_all_key text,
    new_all_key text
) RETURNS jsonb AS $$
DECLARE
    result jsonb;
    metadata_value jsonb;
BEGIN
    IF input_value IS NULL OR jsonb_typeof(input_value) <> 'object' THEN
        RETURN input_value;
    END IF;

    result := _ac_rename_object_key(input_value, old_rule_name_key, new_rule_name_key);

    IF jsonb_typeof(result->'metadata') = 'object' THEN
        metadata_value := result->'metadata';
        metadata_value := _ac_rename_object_key(
            metadata_value,
            old_primary_key,
            new_primary_key
        );
        metadata_value := _ac_rename_object_key(metadata_value, old_all_key, new_all_key);

        IF jsonb_typeof(metadata_value->'condition_trace') = 'object' THEN
            metadata_value := jsonb_set(
                metadata_value,
                '{condition_trace}',
                _ac_rename_condition_trace(
                    metadata_value->'condition_trace',
                    old_rule_name_key,
                    new_rule_name_key
                ),
                false
            );
        END IF;

        result := jsonb_set(result, '{metadata}', metadata_value, false);
    END IF;

    RETURN result;
END;
$$ LANGUAGE plpgsql;
"""

_DROP_HELPER_FUNCTIONS = """
DROP FUNCTION IF EXISTS _ac_rename_event_data(
    jsonb,
    text,
    text,
    text,
    text,
    text,
    text
);
DROP FUNCTION IF EXISTS _ac_rename_condition_trace(jsonb, text, text);
DROP FUNCTION IF EXISTS _ac_rename_control_data(jsonb, text, text);
DROP FUNCTION IF EXISTS _ac_rename_condition_node(jsonb, text, text);
DROP FUNCTION IF EXISTS _ac_rename_object_key(jsonb, text, text);
"""


def _rename_payloads(
    *,
    old_leaf_key: str,
    new_leaf_key: str,
    old_agent_rules_key: str,
    new_agent_rules_key: str,
    old_rule_name_key: str,
    new_rule_name_key: str,
    old_primary_key: str,
    new_primary_key: str,
    old_all_key: str,
    new_all_key: str,
) -> None:
    op.execute(
        f"""
        UPDATE agents
        SET data = _ac_rename_object_key(
            data,
            '{old_agent_rules_key}',
            '{new_agent_rules_key}'
        )
        WHERE jsonb_typeof(data) = 'object'
          AND data ? '{old_agent_rules_key}'
        """
    )

    op.execute(
        f"""
        UPDATE controls
        SET data = _ac_rename_control_data(data, '{old_leaf_key}', '{new_leaf_key}')
        WHERE data::text LIKE '%"{old_leaf_key}"%'
        """
    )

    op.execute(
        f"""
        UPDATE control_versions
        SET snapshot = jsonb_set(
            snapshot,
            '{{data}}',
            _ac_rename_control_data(snapshot->'data', '{old_leaf_key}', '{new_leaf_key}'),
            false
        )
        WHERE jsonb_typeof(snapshot) = 'object'
          AND snapshot ? 'data'
          AND (snapshot->'data')::text LIKE '%"{old_leaf_key}"%'
        """
    )

    op.execute(
        f"""
        UPDATE control_execution_events
        SET data = _ac_rename_event_data(
            data,
            '{old_rule_name_key}',
            '{new_rule_name_key}',
            '{old_primary_key}',
            '{new_primary_key}',
            '{old_all_key}',
            '{new_all_key}'
        )
        WHERE data::text LIKE '%"{old_rule_name_key}"%'
           OR data::text LIKE '%"{old_primary_key}"%'
           OR data::text LIKE '%"{old_all_key}"%'
        """
    )


def upgrade() -> None:
    op.execute(_HELPER_FUNCTIONS)
    try:
        _rename_payloads(
            old_leaf_key="evaluator",
            new_leaf_key="rule",
            old_agent_rules_key="evaluators",
            new_agent_rules_key="rules",
            old_rule_name_key="evaluator_name",
            new_rule_name_key="rule_name",
            old_primary_key="primary_evaluator",
            new_primary_key="primary_rule",
            old_all_key="all_evaluators",
            new_all_key="all_rules",
        )
    finally:
        op.execute(_DROP_HELPER_FUNCTIONS)


def downgrade() -> None:
    op.execute(_HELPER_FUNCTIONS)
    try:
        _rename_payloads(
            old_leaf_key="rule",
            new_leaf_key="evaluator",
            old_agent_rules_key="rules",
            new_agent_rules_key="evaluators",
            old_rule_name_key="rule_name",
            new_rule_name_key="evaluator_name",
            old_primary_key="primary_rule",
            new_primary_key="primary_evaluator",
            old_all_key="all_rules",
            new_all_key="all_evaluators",
        )
    finally:
        op.execute(_DROP_HELPER_FUNCTIONS)
