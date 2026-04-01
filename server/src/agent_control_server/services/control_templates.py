"""Template rendering and error-mapping helpers for control templates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import re2
from agent_control_models import (
    ControlDefinition,
    EnumTemplateParameter,
    JsonValue,
    TemplateControlInput,
    TemplateDefinition,
    TemplateParameterDefinition,
    TemplateValue,
)
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from pydantic import ValidationError

from ..errors import APIValidationError
from .condition_traversal import iter_condition_leaves_with_paths
from .validation_paths import format_field_path

_TEMPLATE_VALUE_MISSING = object()


def can_render_template(template_input: TemplateControlInput) -> bool:
    """Return whether the template input has enough values to render.

    True when every required parameter (that has no default) has a value in
    ``template_values``.  Used to decide between rendered and unrendered
    persistence.
    """
    template = template_input.template
    for name, param in template.parameters.items():
        if not param.required:
            continue
        has_value = name in template_input.template_values
        has_default = getattr(param, "default", None) is not None
        if not has_value and not has_default:
            return False
    return True


@dataclass(frozen=True)
class RenderedTemplateControl:
    """Rendered template result plus reverse mapping for validation errors."""

    control: ControlDefinition
    reverse_path_map: dict[str, str]


def _parameter_error(
    parameter_name: str,
    parameter_definition: TemplateParameterDefinition,
    message: str,
    *,
    code: str = "template_parameter_invalid",
    value: TemplateValue | None = None,
) -> APIValidationError:
    """Create a parameter-focused validation error."""
    return APIValidationError(
        error_code=ErrorCode.TEMPLATE_PARAMETER_INVALID,
        detail=f"Invalid value for parameter '{parameter_definition.label}'",
        resource="Control",
        hint="Update the template parameter values and try again.",
        errors=[
            ValidationErrorItem(
                resource="Control",
                field=f"template_values.{parameter_name}",
                code=code,
                message=message,
                value=value,
                parameter=parameter_name,
                parameter_label=parameter_definition.label,
            )
        ],
    )


def _render_error(
    detail: str,
    *,
    field: str | None = None,
    code: str = "template_render_error",
    message: str | None = None,
) -> APIValidationError:
    """Create a structural template rendering error."""
    errors = None
    if message is not None:
        errors = [
            ValidationErrorItem(
                resource="Control",
                field=field,
                code=code,
                message=message,
                rendered_field=field,
            )
        ]

    return APIValidationError(
        error_code=ErrorCode.TEMPLATE_RENDER_ERROR,
        detail=detail,
        resource="Control",
        hint="Update the template definition and try again.",
        errors=errors,
    )


def _parameter_default(
    parameter_definition: TemplateParameterDefinition,
) -> TemplateValue | object:
    """Return the explicit default for a parameter, if any."""
    # TemplateValue intentionally excludes None, so None continues to mean
    # "no default provided" for current v1 parameter types.
    default = getattr(parameter_definition, "default", None)
    return _TEMPLATE_VALUE_MISSING if default is None else cast(TemplateValue, default)


def _parameter_invalid_type(
    parameter_name: str,
    parameter_definition: TemplateParameterDefinition,
    *,
    expected: str,
    value: TemplateValue,
) -> APIValidationError:
    """Create a standard invalid-type error for template parameter values."""
    return _parameter_error(
        parameter_name,
        parameter_definition,
        f"Parameter '{parameter_definition.label}' must be {expected}.",
        code="invalid_type",
        value=value,
    )


def _require_string_parameter(
    parameter_name: str,
    parameter_definition: TemplateParameterDefinition,
    value: TemplateValue,
    *,
    expected: str,
) -> str:
    """Return a string parameter value or raise a parameter-focused type error."""
    if not isinstance(value, str):
        raise _parameter_invalid_type(
            parameter_name,
            parameter_definition,
            expected=expected,
            value=value,
        )
    return value


def _coerce_parameter_value(
    parameter_name: str,
    parameter_definition: TemplateParameterDefinition,
    value: TemplateValue,
) -> TemplateValue:
    """Validate a concrete parameter value against its parameter definition."""
    parameter_type = parameter_definition.type
    if parameter_type == "string":
        return _require_string_parameter(
            parameter_name,
            parameter_definition,
            value,
            expected="a string",
        )

    if parameter_type == "string_list":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise _parameter_invalid_type(
                parameter_name,
                parameter_definition,
                expected="a list of strings",
                value=value,
            )
        return list(value)

    if parameter_type == "enum":
        enum_value = _require_string_parameter(
            parameter_name,
            parameter_definition,
            value,
            expected="a string enum value",
        )
        enum_definition = cast(EnumTemplateParameter, parameter_definition)
        if enum_value not in enum_definition.allowed_values:
            raise _parameter_error(
                parameter_name,
                parameter_definition,
                (
                    f"Parameter '{parameter_definition.label}' must be one of "
                    f"{enum_definition.allowed_values}."
                ),
                code="invalid_enum_value",
                value=enum_value,
            )
        return enum_value

    if parameter_type == "boolean":
        if type(value) is not bool:
            raise _parameter_invalid_type(
                parameter_name,
                parameter_definition,
                expected="a boolean",
                value=value,
            )
        return value

    if parameter_type == "regex_re2":
        pattern = _require_string_parameter(
            parameter_name,
            parameter_definition,
            value,
            expected="a string regex pattern",
        )
        try:
            re2.compile(pattern)
        except re2.error as exc:
            raise _parameter_error(
                parameter_name,
                parameter_definition,
                (
                    f"Invalid value for parameter '{parameter_definition.label}': "
                    f"Invalid regex pattern: {exc}"
                ),
                code="invalid_regex",
                value=pattern,
            ) from exc
        return pattern

    raise _render_error(
        detail=f"Unsupported template parameter type '{parameter_type}'",
        code="unsupported_parameter_type",
        message=f"Unsupported template parameter type '{parameter_type}'.",
    )


def _resolve_template_values(
    template: TemplateDefinition,
    template_values: Mapping[str, TemplateValue],
) -> dict[str, TemplateValue | object]:
    """Resolve provided parameter values with defaults and validation."""
    unknown_keys = sorted(set(template_values) - set(template.parameters))
    if unknown_keys:
        raise APIValidationError(
            error_code=ErrorCode.TEMPLATE_PARAMETER_INVALID,
            detail="Unknown template parameter(s) supplied",
            resource="Control",
            hint="Remove unknown template parameter keys and try again.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field=f"template_values.{name}",
                    code="unknown_parameter",
                    message=f"Unknown template parameter '{name}'.",
                    parameter=name,
                )
                for name in unknown_keys
            ],
        )

    resolved: dict[str, TemplateValue | object] = {}
    for parameter_name, parameter_definition in template.parameters.items():
        if parameter_name in template_values:
            resolved[parameter_name] = _coerce_parameter_value(
                parameter_name,
                parameter_definition,
                template_values[parameter_name],
            )
            continue

        default_value = _parameter_default(parameter_definition)
        if default_value is not _TEMPLATE_VALUE_MISSING:
            resolved[parameter_name] = _coerce_parameter_value(
                parameter_name,
                parameter_definition,
                cast(TemplateValue, default_value),
            )
            continue

        if parameter_definition.required:
            raise _parameter_error(
                parameter_name,
                parameter_definition,
                f"Missing required parameter '{parameter_definition.label}'.",
                code="missing_parameter",
            )

        resolved[parameter_name] = _TEMPLATE_VALUE_MISSING

    return resolved


def _format_rendered_path(path_parts: list[str | int]) -> str | None:
    """Convert recursive path parts into dotted/bracketed field paths."""
    if not path_parts:
        return None

    components: list[str] = []
    for part in path_parts:
        if isinstance(part, int):
            if not components:
                components.append(f"[{part}]")
            else:
                components[-1] = f"{components[-1]}[{part}]"
            continue
        components.append(part)
    return ".".join(components)


def _render_json_value(
    value: JsonValue,
    *,
    resolved_values: Mapping[str, TemplateValue | object],
    path_parts: list[str | int],
    reverse_path_map: dict[str, str],
    referenced_parameters: set[str],
    template: TemplateDefinition,
) -> JsonValue:
    """Render a JSON value by resolving $param binding objects recursively."""
    if isinstance(value, dict):
        if "$param" in value:
            if len(value) != 1 or not isinstance(value["$param"], str):
                raise _render_error(
                    detail="Invalid $param binding object in template definition",
                    field=_format_rendered_path(path_parts),
                    code="invalid_param_binding",
                    message="A $param binding must be exactly {'$param': '<parameter_name>'}.",
                )

            parameter_name = value["$param"]
            if parameter_name not in template.parameters:
                raise _render_error(
                    detail=f"Template references undefined parameter '{parameter_name}'",
                    field=_format_rendered_path(path_parts),
                    code="undefined_parameter_reference",
                    message=f"Template references undefined parameter '{parameter_name}'.",
                )

            parameter_definition = template.parameters[parameter_name]
            if (
                not parameter_definition.required
                and _parameter_default(parameter_definition) is _TEMPLATE_VALUE_MISSING
            ):
                raise _render_error(
                    detail=(
                        f"Template parameter '{parameter_name}' is optional but referenced in "
                        "definition_template without a default value"
                    ),
                    field=f"template.parameters.{parameter_name}",
                    code="optional_referenced_parameter_requires_default",
                    message=(
                        f"Optional template parameter '{parameter_definition.label}' is "
                        "referenced in the template and must define a default value or be "
                        "marked required."
                    ),
                )

            resolved_value = resolved_values[parameter_name]
            if resolved_value is _TEMPLATE_VALUE_MISSING:
                raise _parameter_error(
                    parameter_name,
                    parameter_definition,
                    f"Missing value for parameter '{parameter_definition.label}'.",
                    code="missing_parameter",
                )

            referenced_parameters.add(parameter_name)
            rendered_field = _format_rendered_path(path_parts)
            if rendered_field is not None:
                reverse_path_map[rendered_field] = parameter_name
            return cast(JsonValue, resolved_value)

        return {
            key: _render_json_value(
                nested_value,
                resolved_values=resolved_values,
                path_parts=[*path_parts, key],
                reverse_path_map=reverse_path_map,
                referenced_parameters=referenced_parameters,
                template=template,
            )
            for key, nested_value in value.items()
        }

    if isinstance(value, list):
        return [
            _render_json_value(
                nested_value,
                resolved_values=resolved_values,
                path_parts=[*path_parts, index],
                reverse_path_map=reverse_path_map,
                referenced_parameters=referenced_parameters,
                template=template,
            )
            for index, nested_value in enumerate(value)
        ]

    return value


def _strip_request_prefix(field: str | None) -> str | None:
    """Remove the request-level 'data.' prefix from raw control validation paths."""
    if field is None:
        return None
    if field.startswith("data."):
        return field.removeprefix("data.")
    if field == "data":
        return None
    return field


def _map_rendered_error_item(
    item: ValidationErrorItem,
    *,
    reverse_path_map: Mapping[str, str],
    template: TemplateDefinition,
) -> tuple[ValidationErrorItem, bool]:
    """Map a rendered control validation item back to a template parameter when possible."""
    rendered_field = _strip_request_prefix(item.field)
    if rendered_field is not None:
        parameter_name = reverse_path_map.get(rendered_field)
        if parameter_name is not None:
            parameter_definition = template.parameters[parameter_name]
            return (
                ValidationErrorItem(
                    resource=item.resource,
                    field=f"template_values.{parameter_name}",
                    code="template_parameter_invalid",
                    message=(
                        f"Invalid value for parameter '{parameter_definition.label}': "
                        f"{item.message}"
                    ),
                    value=item.value,
                    parameter=parameter_name,
                    parameter_label=parameter_definition.label,
                    rendered_field=rendered_field,
                ),
                True,
            )

    return (
        item.model_copy(
            update={
                "field": rendered_field,
                "rendered_field": rendered_field,
            }
        ),
        False,
    )


def remap_template_api_error(
    error: APIValidationError,
    *,
    reverse_path_map: Mapping[str, str],
    template: TemplateDefinition,
) -> APIValidationError:
    """Remap rendered-control validation errors to template parameter paths."""
    remapped_items: list[ValidationErrorItem] = []
    mapped_any = False
    for item in error.errors or []:
        remapped_item, mapped = _map_rendered_error_item(
            item,
            reverse_path_map=reverse_path_map,
            template=template,
        )
        remapped_items.append(remapped_item)
        mapped_any = mapped_any or mapped

    return APIValidationError(
        error_code=(
            ErrorCode.TEMPLATE_PARAMETER_INVALID if mapped_any else ErrorCode.TEMPLATE_RENDER_ERROR
        ),
        detail=error.detail,
        resource=error.resource,
        hint=error.hint,
        errors=remapped_items or error.errors,
    )


def _reject_agent_scoped_evaluators(
    control: ControlDefinition,
    *,
    reverse_path_map: Mapping[str, str],
    template: TemplateDefinition,
) -> None:
    """Reject agent-scoped evaluator references in v1 templates."""
    for field_prefix, leaf in iter_condition_leaves_with_paths(
        control.condition,
        path="condition",
    ):
        leaf_parts = leaf.leaf_parts()
        if leaf_parts is None:
            continue
        _, evaluator_spec = leaf_parts
        if ":" not in evaluator_spec.name:
            continue

        item = ValidationErrorItem(
            resource="Control",
            field=f"{field_prefix}.evaluator.name",
            code="agent_scoped_evaluator_not_supported",
            message=(
                "Agent-scoped evaluators are not supported in control templates."
            ),
        )
        remapped_error, mapped = _map_rendered_error_item(
            item,
            reverse_path_map=reverse_path_map,
            template=template,
        )
        raise APIValidationError(
            error_code=(
                ErrorCode.TEMPLATE_PARAMETER_INVALID if mapped else ErrorCode.TEMPLATE_RENDER_ERROR
            ),
            detail="Agent-scoped evaluators are not supported in control templates",
            resource="Control",
            hint="Use a built-in or package-scoped evaluator in template-backed controls.",
            errors=[remapped_error],
        )


def _collect_param_references(
    value: JsonValue,
    *,
    path_parts: list[str | int],
    template: TemplateDefinition,
    referenced: set[str],
) -> None:
    """Walk definition_template collecting $param references and validating bindings."""
    if isinstance(value, dict):
        if "$param" in value:
            if len(value) != 1 or not isinstance(value["$param"], str):
                raise _render_error(
                    detail="Invalid $param binding object in template definition",
                    field=_format_rendered_path(path_parts),
                    code="invalid_param_binding",
                    message="A $param binding must be exactly {'$param': '<parameter_name>'}.",
                )
            parameter_name = value["$param"]
            if parameter_name not in template.parameters:
                raise _render_error(
                    detail=f"Template references undefined parameter '{parameter_name}'",
                    field=_format_rendered_path(path_parts),
                    code="undefined_parameter_reference",
                    message=f"Template references undefined parameter '{parameter_name}'.",
                )
            # Reject optional params without defaults — they can never render.
            param_def = template.parameters[parameter_name]
            if (
                not param_def.required
                and _parameter_default(param_def) is _TEMPLATE_VALUE_MISSING
            ):
                raise _render_error(
                    detail=(
                        f"Template parameter '{parameter_name}' is optional "
                        "but referenced without a default value"
                    ),
                    field=f"template.parameters.{parameter_name}",
                    code="optional_referenced_parameter_requires_default",
                    message=(
                        f"Optional template parameter '{param_def.label}' is "
                        "referenced in the template and must define a default "
                        "value or be marked required."
                    ),
                )
            referenced.add(parameter_name)
            return

        for key, nested in value.items():
            _collect_param_references(
                nested,
                path_parts=[*path_parts, key],
                template=template,
                referenced=referenced,
            )
    elif isinstance(value, list):
        for idx, nested in enumerate(value):
            _collect_param_references(
                nested,
                path_parts=[*path_parts, idx],
                template=template,
                referenced=referenced,
            )


def validate_template_structure(template: TemplateDefinition) -> None:
    """Validate a template definition's structure without rendering.

    Performs all structural checks that don't require parameter values:
    forbidden top-level keys, legacy format, $param reference validity,
    unused parameter detection, and agent-scoped evaluator rejection.
    """
    definition_template = template.definition_template
    if not isinstance(definition_template, dict):
        raise _render_error(
            detail="Templates must define a top-level control object",
            field="template.definition_template",
            code="invalid_definition_template_type",
            message="definition_template must be a JSON object representing a control definition.",
        )

    for forbidden_key in ("enabled", "name"):
        if forbidden_key in definition_template:
            raise _render_error(
                detail=f"Templates must not define top-level '{forbidden_key}'",
                field=forbidden_key,
                code="forbidden_template_field",
                message=(
                    f"Templates must not define top-level '{forbidden_key}'. "
                    "Manage it outside the template."
                ),
            )

    if "condition" not in definition_template and (
        "selector" in definition_template or "evaluator" in definition_template
    ):
        raise _render_error(
            detail="Templates must use the canonical 'condition' format",
            field="condition",
            code="legacy_condition_format_not_supported",
            message=(
                "Templates must use the canonical 'condition' wrapper instead of "
                "top-level selector/evaluator fields."
            ),
        )

    # Walk the template to validate $param references and collect referenced params.
    referenced: set[str] = set()
    _collect_param_references(
        definition_template,
        path_parts=[],
        template=template,
        referenced=referenced,
    )

    # Reject unused parameters.
    unused = sorted(set(template.parameters) - referenced)
    if unused:
        raise APIValidationError(
            error_code=ErrorCode.TEMPLATE_RENDER_ERROR,
            detail="Template defines parameters that are never referenced",
            resource="Control",
            hint="Remove unused parameters or reference them in definition_template.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field=f"template.parameters.{name}",
                    code="unused_template_parameter",
                    message=f"Template parameter '{name}' is never referenced.",
                    parameter=name,
                    parameter_label=template.parameters[name].label,
                )
                for name in unused
            ],
        )

    # Reject agent-scoped evaluator names baked into the template (not via $param).
    _reject_hardcoded_agent_scoped_evaluators(definition_template)


def validate_partial_template_values(
    template: TemplateDefinition,
    template_values: Mapping[str, TemplateValue],
) -> None:
    """Validate provided template values without requiring completeness.

    Rejects unknown parameter keys and type-checks any values that are
    provided.  Called for unrendered template creation so invalid values
    fail fast instead of persisting silently.
    """
    unknown_keys = sorted(set(template_values) - set(template.parameters))
    if unknown_keys:
        raise APIValidationError(
            error_code=ErrorCode.TEMPLATE_PARAMETER_INVALID,
            detail="Unknown template parameter(s) supplied",
            resource="Control",
            hint="Remove unknown template parameter keys and try again.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field=f"template_values.{name}",
                    code="unknown_parameter",
                    message=f"Unknown template parameter '{name}'.",
                    parameter=name,
                )
                for name in unknown_keys
            ],
        )

    for name, value in template_values.items():
        if name in template.parameters:
            _coerce_parameter_value(name, template.parameters[name], value)


def _reject_hardcoded_agent_scoped_evaluators(
    definition_template: dict[str, JsonValue],
) -> None:
    """Reject agent-scoped evaluator names that are hardcoded in the template."""
    condition = definition_template.get("condition")
    if not isinstance(condition, dict):
        return

    # Walk condition tree tracking the path for accurate error reporting.
    stack: list[tuple[dict[str, JsonValue], str]] = [(condition, "condition")]
    while stack:
        node, path = stack.pop()
        evaluator = node.get("evaluator")
        if isinstance(evaluator, dict):
            name = evaluator.get("name")
            if isinstance(name, str) and ":" in name:
                raise _render_error(
                    detail="Agent-scoped evaluators are not supported in control templates",
                    field=f"{path}.evaluator.name",
                    code="agent_scoped_evaluator_not_supported",
                    message="Agent-scoped evaluators are not supported in control templates.",
                )

        for key in ("and", "or"):
            children = node.get(key)
            if isinstance(children, list):
                for idx, child in enumerate(children):
                    if isinstance(child, dict):
                        stack.append((child, f"{path}.{key}[{idx}]"))

        not_child = node.get("not")
        if isinstance(not_child, dict):
            stack.append((not_child, f"{path}.not"))


def render_template_control_input(
    template_input: TemplateControlInput,
    *,
    enabled: bool = True,
) -> RenderedTemplateControl:
    """Render a template-backed control input into a concrete control definition."""
    template = template_input.template
    definition_template = template.definition_template

    # Reuse structural validation (dict type, forbidden keys, legacy format,
    # $param references, unused params, agent-scoped evaluators).
    validate_template_structure(template)
    assert isinstance(definition_template, dict)  # guaranteed by validate_template_structure

    resolved_values = _resolve_template_values(template, template_input.template_values)
    reverse_path_map: dict[str, str] = {}
    referenced_parameters: set[str] = set()
    rendered_payload = _render_json_value(
        definition_template,
        resolved_values=resolved_values,
        path_parts=[],
        reverse_path_map=reverse_path_map,
        referenced_parameters=referenced_parameters,
        template=template,
    )

    # Note: unused-parameter detection is handled by validate_template_structure
    # (called above).  The referenced_parameters set is still tracked here for
    # the reverse path map used in error remapping.

    try:
        rendered_control = ControlDefinition.model_validate(rendered_payload)
    except ValidationError as exc:
        mapped_items: list[ValidationErrorItem] = []
        mapped_any = False
        for err in exc.errors():
            rendered_field = format_field_path(err.get("loc", ()))
            remapped_item, mapped = _map_rendered_error_item(
                ValidationErrorItem(
                    resource="Control",
                    field=rendered_field,
                    code=err.get("type", "validation_error"),
                    message=err.get("msg", "Validation failed"),
                ),
                reverse_path_map=reverse_path_map,
                template=template,
            )
            mapped_items.append(remapped_item)
            mapped_any = mapped_any or mapped

        raise APIValidationError(
            error_code=(
                ErrorCode.TEMPLATE_PARAMETER_INVALID
                if mapped_any
                else ErrorCode.TEMPLATE_RENDER_ERROR
            ),
            detail="Rendered template did not produce a valid control definition",
            resource="Control",
            hint="Update the template structure or template parameter values and try again.",
            errors=mapped_items,
        ) from exc

    _reject_agent_scoped_evaluators(
        rendered_control,
        reverse_path_map=reverse_path_map,
        template=template,
    )

    concrete_values = {
        name: cast(TemplateValue, value)
        for name, value in resolved_values.items()
        if value is not _TEMPLATE_VALUE_MISSING
    }
    rendered_control = rendered_control.model_copy(
        update={
            "enabled": enabled,
            "template": template,
            "template_values": concrete_values,
        }
    )
    return RenderedTemplateControl(
        control=rendered_control,
        reverse_path_map=reverse_path_map,
    )
