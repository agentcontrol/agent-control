from collections.abc import Sequence
from typing import Any

from agent_control_engine import list_rules
from agent_control_models.agent import Agent as APIAgent
from agent_control_models.agent import StepSchema
from agent_control_models.controls import ControlDefinition, ControlDefinitionRuntime
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.policy import Control as APIControl
from agent_control_models.server import (
    AgentControlsResponse,
    AgentSummary,
    AssocResponse,
    ConflictMode,
    DeletePolicyResponse,
    GetAgentPoliciesResponse,
    GetAgentResponse,
    GetPolicyResponse,
    InitAgentOverwriteChanges,
    InitAgentRequest,
    InitAgentResponse,
    InitAgentRuleRemoval,
    ListAgentsResponse,
    PaginationInfo,
    PatchAgentRequest,
    PatchAgentResponse,
    RemoveAgentControlResponse,
    RuleSchema,
    SetPolicyResponse,
    StepKey,
)
from fastapi import APIRouter, Depends, Query, Request
from jsonschema_rs import ValidationError as JSONSchemaValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_framework import Operation, Principal, get_authorizer, require_operation
from ..db import get_async_db
from ..errors import (
    APIValidationError,
    BadRequestError,
    ConflictError,
    DatabaseError,
    ForbiddenError,
    NotFoundError,
)
from ..logging_utils import get_logger
from ..models import (
    Agent,
    AgentData,
    Control,
    Policy,
    agent_policies,
)
from ..services.agent_names import normalize_agent_name_or_422
from ..services.controls import (
    AgentControlEnabledState,
    AgentControlRenderedState,
    ControlService,
)
from ..services.query_utils import escape_like_pattern
from ..services.rule_utils import (
    parse_rule_ref_full,
    validate_config_against_schema,
)
from ..services.schema_compat import (
    check_schema_compatibility,
    format_compatibility_error,
)

router = APIRouter(prefix="/agents", tags=["agents"])

_logger = get_logger(__name__)

# Cache for built-in rule names (populated on first use)
_BUILTIN_RULE_NAMES: set[str] | None = None

# Pagination constants
_DEFAULT_PAGINATION_OFFSET = 0
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100
_CORRUPTED_AGENT_DATA_MESSAGE = "Stored agent data is corrupted and cannot be parsed."

type StepKeyTuple = tuple[str, str]


def _complete_target_context(
    target_type: object | None,
    target_id: object | None,
) -> dict[str, str] | None:
    """Return target context only when both halves are present strings."""
    if not isinstance(target_type, str) or not isinstance(target_id, str):
        return None
    if not target_type or not target_id:
        return None
    return {"target_type": target_type, "target_id": target_id}


async def _init_agent_target_context(request: Request) -> dict[str, str] | None:
    """Extract optional target context from an ``initAgent`` body."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001  malformed JSON, defer to endpoint validation
        return None
    if not isinstance(body, dict):
        return None
    return _complete_target_context(body.get("target_type"), body.get("target_id"))


def _agent_controls_target_context(request: Request) -> dict[str, str] | None:
    """Extract optional target context from ``GET /agents/{name}/controls``."""
    return _complete_target_context(
        request.query_params.get("target_type"),
        request.query_params.get("target_id"),
    )


async def _authorize_target_read_if_present(
    request: Request,
    context: dict[str, str] | None,
) -> Principal | None:
    """Require target read authorization before returning target-merged controls.

    Agent endpoints that accept optional target context have two separate
    authorization decisions:

    - the endpoint operation itself (for example, ``agents.create``), whose
      result is exposed to the route as ``principal``;
    - the target binding read (``control_bindings.read``), whose result is
      exposed as ``target_principal``.

    Keeping the results separate lets the route verify that the caller's
    namespace and the target's resolved namespace agree before merging
    target-bound controls into the response.
    """
    if context is None:
        return None
    return await get_authorizer(Operation.CONTROL_BINDINGS_READ).authorize(
        request,
        Operation.CONTROL_BINDINGS_READ,
        context,
    )


async def _init_agent_target_principal(request: Request) -> Principal | None:
    return await _authorize_target_read_if_present(
        request,
        await _init_agent_target_context(request),
    )


async def _agent_controls_target_principal(request: Request) -> Principal | None:
    return await _authorize_target_read_if_present(
        request,
        _agent_controls_target_context(request),
    )


def _ensure_target_principal_matches_namespace(
    principal: Principal,
    target_principal: Principal | None,
) -> None:
    """Fail closed if the target authorization resolves to a different namespace."""
    if target_principal is None:
        return
    if target_principal.namespace_key == principal.namespace_key:
        return
    raise ForbiddenError(
        error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
        detail="Target authorization resolved to a different namespace.",
        hint="Ensure the credential is scoped to the requested target and namespace.",
    )


async def _authorize_existing_agent_overwrite(
    request: Request,
    principal: Principal,
) -> None:
    update_principal = await get_authorizer(Operation.AGENTS_UPDATE).authorize(
        request,
        Operation.AGENTS_UPDATE,
    )
    if update_principal.namespace_key == principal.namespace_key:
        return
    raise ForbiddenError(
        error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
        detail="Update authorization resolved to a different namespace.",
        hint="Ensure the credential is scoped to the requested agent namespace.",
    )


# =============================================================================
# List Agents Models
# =============================================================================


def _get_builtin_rule_names() -> set[str]:
    """Get built-in rule names (cached)."""
    global _BUILTIN_RULE_NAMES
    if _BUILTIN_RULE_NAMES is None:
        _BUILTIN_RULE_NAMES = set(list_rules().keys())
    return _BUILTIN_RULE_NAMES


def _validate_controls_for_agent(agent: Agent, controls: list[Control]) -> list[str]:
    """Validate controls can run on this agent."""
    errors: list[str] = []

    # Parse agent's registered rules
    try:
        agent_data = AgentData.model_validate(agent.data)
    except ValidationError:
        return [f"Agent '{agent.name}' has corrupted data"]

    agent_rules = {e.name: e for e in (agent_data.rules or [])}

    for control in controls:
        # Skip unrendered template controls - they have no rules to validate.
        if (
            isinstance(control.data, dict)
            and control.data.get("template") is not None
            and control.data.get("condition") is None
        ):
            continue

        try:
            control_definition = ControlDefinitionRuntime.model_validate(control.data)
        except ValidationError:
            errors.append(f"Control '{control.name}' has corrupted data")
            continue

        for _, rule_cfg in control_definition.iter_condition_leaf_parts():
            rule_name = rule_cfg.name
            parsed = parse_rule_ref_full(rule_name)
            if parsed.type != "agent":
                continue  # Built-in/external rule, already validated at control creation

            # Agent-scoped rule - check if target matches this agent
            if parsed.namespace != agent.name:
                errors.append(
                    f"Control '{control.name}' references rule '{rule_name}' "
                    f"which belongs to agent '{parsed.namespace}', not '{agent.name}'"
                )
                continue

            # Check if rule exists on this agent
            if parsed.local_name not in agent_rules:
                errors.append(
                    f"Control '{control.name}' references rule '{parsed.local_name}' "
                    f"which is not registered with agent '{agent.name}'. "
                    f"Register it via initAgent or use a different rule."
                )
                continue

            # Validate config against schema
            registered_rule = agent_rules[parsed.local_name]
            if registered_rule.config_schema:
                try:
                    validate_config_against_schema(
                        rule_cfg.config,
                        registered_rule.config_schema,
                    )
                except JSONSchemaValidationError as e:
                    errors.append(
                        f"Control '{control.name}' invalid config for "
                        f"'{parsed.local_name}': {e.message}"
                    )

    return errors


def _find_referencing_controls_for_removed_rules(
    controls: Sequence[APIControl],
    agent_name: str,
    remove_rule_set: set[str],
) -> list[tuple[str, str]]:
    """Return sorted unique control/rule pairs blocking rule removal."""
    referencing_control_set: set[tuple[str, str]] = set()

    for ctrl in controls:
        if not isinstance(ctrl.control, ControlDefinition):
            continue  # Skip unrendered template controls
        for _, rule_spec in ctrl.control.iter_condition_leaf_parts():
            rule_ref = rule_spec.name
            if ":" not in rule_ref:
                continue
            ref_agent, ref_eval = rule_ref.split(":", 1)
            if ref_agent == agent_name and ref_eval in remove_rule_set:
                referencing_control_set.add((ctrl.name, ref_eval))

    return sorted(referencing_control_set, key=lambda item: (item[0], item[1]))


async def _validate_policy_controls_for_agent(
    agent: Agent, policy_id: int, db: AsyncSession, *, namespace_key: str
) -> list[str]:
    """Validate all controls in a policy can run on this agent."""
    controls = await ControlService(db).list_controls_for_policy(
        policy_id, namespace_key=namespace_key
    )
    return _validate_controls_for_agent(agent, controls)


def _step_registration_changed(existing_step: StepSchema, incoming_step: StepSchema) -> bool:
    """Return True when non-key step registration fields differ."""
    return (
        existing_step.description != incoming_step.description
        or existing_step.input_schema != incoming_step.input_schema
        or existing_step.output_schema != incoming_step.output_schema
        or existing_step.metadata != incoming_step.metadata
    )


def _step_key_model(step_key: StepKeyTuple) -> StepKey:
    """Convert an internal step tuple key to API model."""
    step_type, step_name = step_key
    return StepKey(type=step_type, name=step_name)


async def _build_overwrite_rule_removals(
    agent: Agent,
    removed_rules: set[str],
    db: AsyncSession,
    *,
    namespace_key: str,
) -> list[InitAgentRuleRemoval]:
    """Build rule removal details, including active-control references."""
    if not removed_rules:
        return []

    try:
        controls = await ControlService(db).list_controls_for_agent(
            agent.name,
            namespace_key=namespace_key,
            allow_invalid_step_name_regex=True,
        )
    except APIValidationError:
        _logger.warning(
            "Skipping rule removal reference checks for agent '%s' "
            "due to invalid control data",
            agent.name,
            exc_info=True,
        )
        return [InitAgentRuleRemoval(name=name) for name in sorted(removed_rules)]

    references_by_rule: dict[str, set[tuple[int, str]]] = {}
    for control in controls:
        if not isinstance(control.control, ControlDefinition):
            continue  # Skip unrendered template controls
        for _, rule_spec in control.control.iter_condition_leaf_parts():
            rule_ref = rule_spec.name
            parsed = parse_rule_ref_full(rule_ref)
            if parsed.type != "agent":
                continue
            if parsed.namespace != agent.name:
                continue
            if parsed.local_name not in removed_rules:
                continue
            references_by_rule.setdefault(parsed.local_name, set()).add(
                (control.id, control.name)
            )

    removals: list[InitAgentRuleRemoval] = []
    for rule_name in sorted(removed_rules):
        references = references_by_rule.get(rule_name)
        if references is None:
            removals.append(InitAgentRuleRemoval(name=rule_name))
            continue
        sorted_references = sorted(references, key=lambda item: (item[1], item[0]))
        removals.append(
            InitAgentRuleRemoval(
                name=rule_name,
                referenced_by_active_controls=True,
                control_ids=[control_id for control_id, _ in sorted_references],
                control_names=[control_name for _, control_name in sorted_references],
            )
        )
    return removals


@router.get(
    "",
    response_model=ListAgentsResponse,
    summary="List all agents",
    response_description="Paginated list of agent summaries",
)
async def list_agents(
    cursor: str | None = None,
    limit: int = _DEFAULT_PAGINATION_LIMIT,
    name: str | None = None,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_READ)),
) -> ListAgentsResponse:
    """
    List all registered agents with cursor-based pagination.

    Returns a summary of each agent including identifier, policy associations,
    and counts of registered steps and rules. Results are scoped to
    the request's namespace; agents in other namespaces are not visible.

    Args:
        cursor: Optional cursor for pagination (last agent name from previous page)
        limit: Pagination limit (default 20, max 100)
        name: Optional name filter (case-insensitive partial match)
        db: Database session (injected)
        principal: Authorized request principal

    Returns:
        ListAgentsResponse with agent summaries and pagination info
    """
    namespace_key = principal.namespace_key

    # Clamp limit
    limit = min(max(1, limit), _MAX_PAGINATION_LIMIT)

    # Build base filter for name search
    name_filter = Agent.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\") if name else None

    # Get total count (with name filter if provided)
    count_query = (
        select(func.count()).select_from(Agent).where(Agent.namespace_key == namespace_key)
    )
    if name_filter is not None:
        count_query = count_query.where(name_filter)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Build query with cursor-based pagination
    # Order by created_at DESC, then by name DESC for stable ordering
    query = (
        select(Agent)
        .where(Agent.namespace_key == namespace_key)
        .order_by(Agent.created_at.desc(), Agent.name.desc())
    )

    # Apply name filter if provided
    if name_filter is not None:
        query = query.where(name_filter)

    # If cursor provided, filter to get items after the cursor.
    # The cursor lookup is namespace-scoped so a duplicate name in
    # another namespace cannot redirect pagination.
    if cursor:
        cursor_name = normalize_agent_name_or_422(cursor, field_name="cursor")
        cursor_agent_result = await db.execute(
            select(Agent).where(
                Agent.name == cursor_name,
                Agent.namespace_key == namespace_key,
            )
        )
        cursor_agent = cursor_agent_result.scalars().first()
        if cursor_agent:
            query = query.where(
                (Agent.created_at < cursor_agent.created_at)
                | ((Agent.created_at == cursor_agent.created_at) & (Agent.name < cursor_agent.name))
            )

    # Fetch limit + 1 to check if there are more pages
    query = query.limit(limit + 1)
    result = await db.execute(query)
    agents = result.scalars().all()

    # Check if there are more pages
    has_more = len(agents) > limit
    if has_more:
        agents = agents[:-1]  # Remove the extra item

    # Determine next cursor (name of last agent in this page)
    next_cursor: str | None = None
    if has_more and agents:
        next_cursor = agents[-1].name

    control_counts_map: dict[str, int] = {}
    policy_ids_map: dict[str, list[int]] = {}
    control_service = ControlService(db)

    if agents:
        agent_names = [agent.name for agent in agents]

        policy_ids_query = (
            select(
                agent_policies.c.agent_name,
                agent_policies.c.policy_id,
            )
            .where(
                agent_policies.c.namespace_key == namespace_key,
                agent_policies.c.agent_name.in_(agent_names),
            )
            .order_by(agent_policies.c.agent_name, agent_policies.c.policy_id)
        )
        policy_ids_result = await db.execute(policy_ids_query)
        for assoc_agent_name, policy_id in policy_ids_result.all():
            policy_ids_map.setdefault(assoc_agent_name, []).append(policy_id)

        control_counts_map = await control_service.list_active_control_counts_by_agent(
            agent_names,
            namespace_key=namespace_key,
        )

    # Build summaries
    summaries: list[AgentSummary] = []
    for agent in agents:
        step_count = 0
        rule_count = 0

        # Parse agent data to get counts
        try:
            data_model = AgentData.model_validate(agent.data)
            step_count = len(data_model.steps or [])
            rule_count = len(data_model.rules or [])
        except ValidationError:
            # If data is corrupted, log and use zero counts
            _logger.warning("Agent '%s' has invalid data, using zero counts", agent.name)

        # Get active controls count from batched query result
        active_controls = control_counts_map.get(agent.name, 0)

        policy_ids = policy_ids_map.get(agent.name, [])

        summaries.append(
            AgentSummary(
                agent_name=agent.name,
                policy_ids=policy_ids,
                created_at=agent.created_at.isoformat() if agent.created_at else None,
                step_count=step_count,
                rule_count=rule_count,
                active_controls_count=active_controls,
            )
        )

    return ListAgentsResponse(
        agents=summaries,
        pagination=PaginationInfo(
            limit=limit,
            total=total,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


@router.post(
    "/initAgent",
    response_model=InitAgentResponse,
    summary="Initialize or update an agent",
    response_description="Agent registration status with active controls",
)
async def init_agent(
    request: InitAgentRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_CREATE)),
    target_principal: Principal | None = Depends(_init_agent_target_principal),
) -> InitAgentResponse:
    """
    Register a new agent or update an existing agent's steps and metadata.

    This endpoint is idempotent:
    - If the agent name doesn't exist, creates a new agent
    - If the agent name exists, updates registration data in place

    conflict_mode controls registration conflict handling:
    - strict (default): preserve compatibility checks and conflict errors
    - overwrite: latest init payload replaces steps/rules and returns change summary

    The returned ``controls`` list is the de-duplicated union of the agent's
    direct controls, policy-derived controls, and (when ``target_type`` and
    ``target_id`` are both supplied on the request) controls attached to that
    target via enabled bindings in the same namespace. The same merge applies
    on ``GET /agents/{name}/controls`` and ``POST /evaluation``. Bindings can
    pre-exist the agent row, so a newly created agent that registers with
    target context can observe target controls immediately.

    Args:
        request: Agent metadata and step schemas
        db: Database session (injected)
        principal: Authorized request principal for the agent create operation
        target_principal: Optional principal from the target binding read check

    Returns:
        InitAgentResponse with created flag and the effective controls
    """
    namespace_key = principal.namespace_key
    _ensure_target_principal_matches_namespace(principal, target_principal)

    # Check for rule name collisions with built-in rules
    builtin_names = _get_builtin_rule_names()
    for rule in request.rules:
        if rule.name in builtin_names:
            raise ConflictError(
                error_code=ErrorCode.RULE_NAME_CONFLICT,
                detail=f"Rule name '{rule.name}' conflicts with built-in rule.",
                resource="Rule",
                resource_id=rule.name,
                hint="Choose a different name that does not conflict with built-in rules.",
                errors=[
                    ValidationErrorItem(
                        resource="Rule",
                        field="name",
                        code="name_conflict",
                        message=f"Name '{rule.name}' conflicts with a built-in rule",
                        value=rule.name,
                    )
                ],
            )

    # Build incoming_steps_by_key and validate no duplicates in single pass
    incoming_steps_by_key: dict[StepKeyTuple, StepSchema] = {}
    for step in request.steps:
        step_key: StepKeyTuple = (step.type, step.name)
        if step_key in incoming_steps_by_key:
            raise BadRequestError(
                error_code=ErrorCode.VALIDATION_ERROR,
                detail=f"Duplicate step name detected: type='{step.type}', name='{step.name}'. "
                f"Each step must have a unique (type, name) combination within an agent.",
                errors=[
                    ValidationErrorItem(
                        resource="Step",
                        field="name",
                        code="duplicate_step_name",
                        message=(
                            f"Step (type='{step.type}', name='{step.name}') "
                            f"appears multiple times in request"
                        ),
                    )
                ],
            )
        incoming_steps_by_key[step_key] = step

    result = await db.execute(
        select(Agent).where(
            Agent.name == request.agent.agent_name,
            Agent.namespace_key == namespace_key,
        )
    )
    existing: Agent | None = result.scalars().first()

    created = False

    if existing is None:
        created = True

        data_model = AgentData(
            agent_metadata=request.agent.model_dump(mode="json"),
            steps=list(request.steps),
            rules=list(request.rules),
        )

        new_agent = Agent(
            name=request.agent.agent_name,
            namespace_key=namespace_key,
            data=data_model.model_dump(mode="json"),
        )
        db.add(new_agent)
        try:
            await db.commit()
            _logger.info(
                f"Created agent '{request.agent.agent_name}' with {len(request.steps)} steps, "
                f"{len(request.rules)} rules"
            )
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to create agent '{request.agent.agent_name}' ({request.agent.agent_name})",
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to create agent '{request.agent.agent_name}': database error",
                resource="Agent",
                operation="create",
            )

        # Fall through to the terminal resolution so a newly created agent
        # registering with target context picks up pre-existing bindings.
        controls = await ControlService(db).list_controls_for_agent(
            new_agent.name,
            namespace_key=namespace_key,
            target_type=request.target_type,
            target_id=request.target_id,
        )
        return InitAgentResponse(created=created, controls=controls)

    if request.force_replace or request.conflict_mode == ConflictMode.OVERWRITE:
        await _authorize_existing_agent_overwrite(http_request, principal)

    # Parse existing data via AgentData Pydantic model
    try:
        data_model = AgentData.model_validate(existing.data)
    except ValidationError:
        if not request.force_replace:
            _logger.error(
                f"Failed to parse existing agent data for '{request.agent.agent_name}'",
                exc_info=True,
            )
            raise APIValidationError(
                error_code=ErrorCode.CORRUPTED_DATA,
                detail=(
                    f"Agent '{request.agent.agent_name}' has corrupted data and cannot be updated"
                ),
                resource="Agent",
                hint="Set force_replace=true in the request to replace the corrupted data.",
                errors=[
                    ValidationErrorItem(
                        resource="Agent",
                        field="data",
                        code="corrupted_data",
                        message=_CORRUPTED_AGENT_DATA_MESSAGE,
                    )
                ],
            )
        # User explicitly requested replacement
        _logger.warning(
            f"Force-replacing corrupted data for agent '{request.agent.agent_name}' "
            "due to force_replace=true.",
            exc_info=True,
        )
        data_model = AgentData(agent_metadata={}, steps=[], rules=[])

    steps_changed = False
    rules_changed = False
    force_write = request.force_replace  # Always persist when force_replace=true
    overwrite_applied = False
    overwrite_changes = InitAgentOverwriteChanges()

    # --- Update agent metadata ---
    new_metadata = request.agent.model_dump(mode="json")
    metadata_changed = data_model.agent_metadata != new_metadata
    if metadata_changed:
        data_model.agent_metadata = new_metadata

    new_steps: list[StepSchema]
    new_rules: list[RuleSchema]

    if request.conflict_mode == ConflictMode.OVERWRITE:
        # Latest-init-wins: overwrite steps/rules exactly with incoming payload.
        existing_steps = list(data_model.steps or [])
        existing_steps_by_key = {(step.type, step.name): step for step in existing_steps}
        existing_step_keys = set(existing_steps_by_key)
        incoming_step_keys = set(incoming_steps_by_key)

        steps_added_keys = sorted(incoming_step_keys - existing_step_keys)
        steps_removed_keys = sorted(existing_step_keys - incoming_step_keys)
        steps_updated_keys = sorted(
            key
            for key in (existing_step_keys & incoming_step_keys)
            if _step_registration_changed(existing_steps_by_key[key], incoming_steps_by_key[key])
        )

        existing_rules = list(data_model.rules or [])
        existing_rules_by_name: dict[str, RuleSchema] = {
            rule.name: rule for rule in existing_rules
        }
        incoming_rules_by_name: dict[str, RuleSchema] = {
            rule.name: rule for rule in request.rules
        }
        existing_rule_names = set(existing_rules_by_name)
        incoming_rule_names = set(incoming_rules_by_name)

        rules_added_names = sorted(incoming_rule_names - existing_rule_names)
        rules_removed_names = sorted(existing_rule_names - incoming_rule_names)
        rules_updated_names = sorted(
            name
            for name in (existing_rule_names & incoming_rule_names)
            if (
                existing_rules_by_name[name].config_schema
                != incoming_rules_by_name[name].config_schema
                or existing_rules_by_name[name].description
                != incoming_rules_by_name[name].description
            )
        )

        rule_removals: list[InitAgentRuleRemoval] = []
        if rules_removed_names:
            rule_removals = await _build_overwrite_rule_removals(
                existing,
                set(rules_removed_names),
                db,
                namespace_key=namespace_key,
            )

        overwrite_changes = InitAgentOverwriteChanges(
            metadata_changed=metadata_changed,
            steps_added=[_step_key_model(step_key) for step_key in steps_added_keys],
            steps_updated=[_step_key_model(step_key) for step_key in steps_updated_keys],
            steps_removed=[_step_key_model(step_key) for step_key in steps_removed_keys],
            rules_added=rules_added_names,
            rules_updated=rules_updated_names,
            rules_removed=rules_removed_names,
            rule_removals=rule_removals,
        )

        steps_changed = bool(steps_added_keys or steps_updated_keys or steps_removed_keys)
        rules_changed = bool(
            rules_added_names or rules_updated_names or rules_removed_names
        )
        overwrite_applied = bool(metadata_changed or steps_changed or rules_changed)

        new_steps = list(request.steps)
        new_rules = list(request.rules)
        data_model.steps = new_steps
        data_model.rules = new_rules
    else:
        # --- Process steps ---
        # Note: incoming_steps_by_key already built during validation above
        new_steps = []
        seen_steps: set[StepKeyTuple] = set()

        for step in data_model.steps or []:
            key: StepKeyTuple = (step.type, step.name)
            if key in incoming_steps_by_key:
                if key not in seen_steps:
                    incoming_step = incoming_steps_by_key[key]

                    # Compare only schema fields (type/name already matched by key)
                    # Avoid model_dump() allocations by direct field comparison
                    if (
                        step.input_schema != incoming_step.input_schema
                        or step.output_schema != incoming_step.output_schema
                    ):
                        raise ConflictError(
                            error_code=ErrorCode.SCHEMA_INCOMPATIBLE,
                            detail=(
                                "Step schema conflict for "
                                f"(type='{step.type}', name='{step.name}'). "
                                f"A step with this name already exists with a different schema."
                            ),
                            resource="Step",
                            resource_id=step.name,
                            hint=(
                                "Please use a different step name or ensure schemas match exactly."
                            ),
                            errors=[
                                ValidationErrorItem(
                                    resource="Step",
                                    field="schema",
                                    code="schema_mismatch",
                                    message=(
                                        f"Existing schema differs from incoming schema "
                                        f"for step '{step.name}'"
                                    ),
                                )
                            ],
                        )

                    new_steps.append(incoming_step)
                    seen_steps.add(key)
            else:
                new_steps.append(step)

        for key, step in incoming_steps_by_key.items():
            if key not in seen_steps:
                new_steps.append(step)
                steps_changed = True

        data_model.steps = new_steps

        # --- Process rules with schema compatibility check ---
        incoming_rules_by_name = {rule.name: rule for rule in request.rules}
        existing_rules_by_name = {
            rule.name: rule for rule in (data_model.rules or [])
        }
        new_rules = []

        # Check existing rules for compatibility
        for name, existing_rule in existing_rules_by_name.items():
            if name in incoming_rules_by_name:
                incoming_rule = incoming_rules_by_name[name]
                old_schema = existing_rule.config_schema
                new_schema = incoming_rule.config_schema

                # Short-circuit: only check compatibility if schemas differ
                if old_schema != new_schema:
                    is_compatible, compat_errors = check_schema_compatibility(
                        old_schema, new_schema
                    )
                    if not is_compatible:
                        raise ConflictError(
                            error_code=ErrorCode.SCHEMA_INCOMPATIBLE,
                            detail=format_compatibility_error(name, compat_errors),
                            resource="Rule",
                            resource_id=name,
                            hint="Ensure backward compatibility or use a new rule name.",
                            errors=[
                                ValidationErrorItem(
                                    resource="Rule",
                                    field="config_schema",
                                    code="schema_incompatible",
                                    message=err,
                                )
                                for err in compat_errors
                            ],
                        )

                # Check if rule changed (compare fields directly, avoid model_dump())
                if (
                    existing_rule.config_schema != incoming_rule.config_schema
                    or existing_rule.description != incoming_rule.description
                ):
                    rules_changed = True
                new_rules.append(incoming_rule)
            else:
                # Keep existing rule not in incoming request
                new_rules.append(existing_rule)

        # Add new rules
        for name, rule in incoming_rules_by_name.items():
            if name not in existing_rules_by_name:
                new_rules.append(rule)
                rules_changed = True

        data_model.rules = new_rules

    if (
        not request.force_replace
        and request.conflict_mode != ConflictMode.OVERWRITE
        and (steps_changed or rules_changed or metadata_changed)
    ):
        await _authorize_existing_agent_overwrite(http_request, principal)

    if steps_changed or rules_changed or metadata_changed or force_write:
        existing.data = data_model.model_dump(mode="json")

        try:
            await db.commit()
            _logger.info(
                f"Updated agent '{request.agent.agent_name}' with {len(new_steps)} steps, "
                f"{len(new_rules)} rules"
            )
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to update agent '{request.agent.agent_name}' ({request.agent.agent_name})",
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to update agent '{request.agent.agent_name}': database error",
                resource="Agent",
                operation="update",
            )

    controls = await ControlService(db).list_controls_for_agent(
        existing.name,
        namespace_key=namespace_key,
        target_type=request.target_type,
        target_id=request.target_id,
    )

    return InitAgentResponse(
        created=created,
        controls=controls,
        overwrite_applied=overwrite_applied,
        overwrite_changes=overwrite_changes,
    )


@router.get(
    "/{agent_name}",
    response_model=GetAgentResponse,
    summary="Get agent details",
    response_description="Agent metadata and registered steps",
)
async def get_agent(
    agent_name: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_READ)),
) -> GetAgentResponse:
    """
    Retrieve agent metadata and all registered steps.

    Returns the latest version of each step (deduplicated by type+name).

    Args:
        agent_name: Agent identifier
        db: Database session (injected)
        principal: Authorized request principal

    Returns:
        GetAgentResponse with agent metadata and step list

    Raises:
        HTTPException 404: Agent not found
        HTTPException 422: Agent data is corrupted
    """
    namespace_key = principal.namespace_key
    agent_name = normalize_agent_name_or_422(agent_name)
    result = await db.execute(
        select(Agent).where(Agent.name == agent_name, Agent.namespace_key == namespace_key)
    )
    existing: Agent | None = result.scalars().first()
    if existing is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with name '{agent_name}' not found",
            resource="Agent",
            resource_id=str(agent_name),
            hint=(
                "Verify the agent name is correct and the agent has been registered via initAgent."
            ),
        )

    try:
        data_model = AgentData.model_validate(existing.data)
    except ValidationError:
        _logger.error(
            f"Failed to parse agent data for agent '{existing.name}' ({agent_name})",
            exc_info=True,
        )
        raise APIValidationError(
            error_code=ErrorCode.CORRUPTED_DATA,
            detail=f"Agent data is corrupted for agent '{existing.name}'",
            resource="Agent",
            hint="The agent's stored data is invalid. Re-register the agent with initAgent.",
        )

    try:
        steps_by_key: dict[StepKeyTuple, StepSchema] = {}
        for step in data_model.steps or []:
            key: StepKeyTuple = (step.type, step.name)
            steps_by_key[key] = step
        latest_steps: list[StepSchema] = list(steps_by_key.values())
        agent_meta = APIAgent.model_validate(data_model.agent_metadata)
    except ValidationError:
        _logger.error(
            f"Failed to parse agent metadata for agent '{existing.name}' ({agent_name})",
            exc_info=True,
        )
        raise APIValidationError(
            error_code=ErrorCode.CORRUPTED_DATA,
            detail=f"Agent metadata is corrupted for agent '{existing.name}'",
            resource="Agent",
            hint="The agent's metadata is invalid. Re-register the agent with initAgent.",
        )

    return GetAgentResponse(agent=agent_meta, steps=latest_steps, rules=data_model.rules)


async def _get_agent_or_404(
    agent_name: str,
    db: AsyncSession,
    *,
    namespace_key: str,
) -> Agent:
    """Get an agent in ``namespace_key`` or raise AGENT_NOT_FOUND.

    The lookup is always namespace-scoped: an agent that exists only in
    another namespace surfaces as 404 (non-disclosing) so duplicate
    names across namespaces - which the schema explicitly permits -
    cannot be addressed across the namespace boundary.
    """
    normalized_agent_name = normalize_agent_name_or_422(agent_name)
    stmt = select(Agent).where(
        Agent.name == normalized_agent_name,
        Agent.namespace_key == namespace_key,
    )
    result = await db.execute(stmt)
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with name '{normalized_agent_name}' not found",
            resource="Agent",
            resource_id=normalized_agent_name,
            hint="Verify the agent name is correct and the agent has been registered.",
        )
    return agent


@router.post(
    "/{agent_name}/policies/{policy_id}",
    response_model=AssocResponse,
    summary="Associate policy with agent",
    response_description="Success confirmation",
)
async def add_agent_policy(
    agent_name: str,
    policy_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> AssocResponse:
    """Associate a policy with an agent (idempotent)."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)

    policy_result = await db.execute(
        select(Policy).where(Policy.id == policy_id, Policy.namespace_key == namespace_key)
    )
    policy: Policy | None = policy_result.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    validation_errors = await _validate_policy_controls_for_agent(
        agent, policy_id, db, namespace_key=namespace_key
    )
    if validation_errors:
        raise BadRequestError(
            error_code=ErrorCode.POLICY_CONTROL_INCOMPATIBLE,
            detail="Policy contains controls incompatible with this agent",
            hint="Ensure all controls in the policy are compatible with this agent's rules.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field="rule",
                    code="incompatible",
                    message=err,
                )
                for err in validation_errors
            ],
        )

    try:
        stmt = (
            pg_insert(agent_policies)
            .values(
                namespace_key=namespace_key,
                agent_name=agent.name,
                policy_id=policy_id,
            )
            .on_conflict_do_nothing()
        )
        await db.execute(stmt)
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to associate policy '%s' with agent '%s'",
            policy_id,
            agent.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to associate policy with agent '{agent.name}': database error",
            resource="Agent",
            operation="add policy association",
        )

    return AssocResponse(success=True)


@router.post(
    "/{agent_name}/policy/{policy_id}",
    response_model=SetPolicyResponse,
    summary="Assign policy to agent (compatibility)",
    response_description="Success status with previous policy ID",
)
async def set_agent_policy(
    agent_name: str,
    policy_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> SetPolicyResponse:
    """Compatibility endpoint that replaces all policy associations with one policy."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)

    policy_result = await db.execute(
        select(Policy).where(Policy.id == policy_id, Policy.namespace_key == namespace_key)
    )
    policy: Policy | None = policy_result.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    validation_errors = await _validate_policy_controls_for_agent(
        agent, policy_id, db, namespace_key=namespace_key
    )
    if validation_errors:
        raise BadRequestError(
            error_code=ErrorCode.POLICY_CONTROL_INCOMPATIBLE,
            detail="Policy contains controls incompatible with this agent",
            hint="Ensure all controls in the policy are compatible with this agent's rules.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field="rule",
                    code="incompatible",
                    message=err,
                )
                for err in validation_errors
            ],
        )

    existing_policies_result = await db.execute(
        select(agent_policies.c.policy_id)
        .where(
            agent_policies.c.namespace_key == namespace_key,
            agent_policies.c.agent_name == agent.name,
        )
        .order_by(agent_policies.c.policy_id)
    )
    existing_policy_ids = [row[0] for row in existing_policies_result.all()]
    old_policy_id = existing_policy_ids[0] if existing_policy_ids else None

    try:
        await db.execute(
            delete(agent_policies).where(
                agent_policies.c.namespace_key == namespace_key,
                agent_policies.c.agent_name == agent.name,
            )
        )
        await db.execute(
            pg_insert(agent_policies)
            .values(
                namespace_key=namespace_key,
                agent_name=agent.name,
                policy_id=policy_id,
            )
            .on_conflict_do_nothing()
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to assign policy '%s' to agent '%s'",
            policy_id,
            agent.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to assign policy to agent '{agent.name}': database error",
            resource="Agent",
            operation="assign policy",
        )

    return SetPolicyResponse(success=True, old_policy_id=old_policy_id)


@router.get(
    "/{agent_name}/policies",
    response_model=GetAgentPoliciesResponse,
    summary="List policies associated with agent",
    response_description="List of policy IDs",
)
async def get_agent_policies(
    agent_name: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_READ)),
) -> GetAgentPoliciesResponse:
    """List policy IDs associated with an agent."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)
    result = await db.execute(
        select(agent_policies.c.policy_id)
        .where(
            agent_policies.c.namespace_key == namespace_key,
            agent_policies.c.agent_name == agent.name,
        )
        .order_by(agent_policies.c.policy_id)
    )
    return GetAgentPoliciesResponse(policy_ids=[row[0] for row in result.all()])


@router.get(
    "/{agent_name}/policy",
    response_model=GetPolicyResponse,
    summary="Get agent's assigned policy (compatibility)",
    response_description="Policy ID",
)
async def get_agent_policy(
    agent_name: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_READ)),
) -> GetPolicyResponse:
    """Compatibility endpoint that returns the first associated policy."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)
    policy_result = await db.execute(
        select(Policy.id)
        .join(
            agent_policies,
            (agent_policies.c.policy_id == Policy.id)
            & (agent_policies.c.namespace_key == Policy.namespace_key),
        )
        .where(
            agent_policies.c.namespace_key == namespace_key,
            agent_policies.c.agent_name == agent.name,
        )
        .order_by(Policy.id)
        .limit(1)
    )
    policy_id = policy_result.scalars().first()
    if policy_id is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Agent '{agent.name}' has no policy assigned",
            resource="Policy",
            hint="Assign a policy to the agent using POST /{agent_name}/policies/{policy_id}.",
        )
    return GetPolicyResponse(policy_id=policy_id)


@router.delete(
    "/{agent_name}/policies/{policy_id}",
    response_model=AssocResponse,
    summary="Remove policy association from agent",
    response_description="Success confirmation",
)
async def remove_agent_policy(
    agent_name: str,
    policy_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> AssocResponse:
    """Remove a policy association from an agent.

    Idempotent for existing resources: removing a non-associated link is a no-op.
    Missing agent/policy resources still return 404.
    """
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)

    policy_result = await db.execute(
        select(Policy.id).where(Policy.id == policy_id, Policy.namespace_key == namespace_key)
    )
    if policy_result.first() is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    try:
        await db.execute(
            delete(agent_policies).where(
                (agent_policies.c.namespace_key == namespace_key)
                & (agent_policies.c.agent_name == agent.name)
                & (agent_policies.c.policy_id == policy_id)
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to remove policy '%s' from agent '%s'",
            policy_id,
            agent.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to remove policy association from agent '{agent.name}': database error",
            resource="Agent",
            operation="remove policy association",
        )

    return AssocResponse(success=True)


@router.delete(
    "/{agent_name}/policies",
    response_model=AssocResponse,
    summary="Remove all policy associations from agent",
    response_description="Success confirmation",
)
async def remove_all_agent_policies(
    agent_name: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> AssocResponse:
    """Remove all policy associations from an agent."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)

    try:
        await db.execute(
            delete(agent_policies).where(
                agent_policies.c.namespace_key == namespace_key,
                agent_policies.c.agent_name == agent.name,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to remove all policies from agent '%s'",
            agent.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to remove policy associations from agent '{agent.name}': database error"
            ),
            resource="Agent",
            operation="remove all policy associations",
        )

    return AssocResponse(success=True)


@router.delete(
    "/{agent_name}/policy",
    response_model=DeletePolicyResponse,
    summary="Remove agent's policy assignment (compatibility)",
    response_description="Success confirmation",
)
async def delete_agent_policy(
    agent_name: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> DeletePolicyResponse:
    """Compatibility endpoint that removes all policy associations."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)

    existing_policy_result = await db.execute(
        select(agent_policies.c.policy_id)
        .where(
            agent_policies.c.namespace_key == namespace_key,
            agent_policies.c.agent_name == agent.name,
        )
        .limit(1)
    )
    if existing_policy_result.first() is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Agent '{agent.name}' has no policy assigned",
            resource="Policy",
            hint="The agent does not have a policy to remove.",
        )

    try:
        await db.execute(
            delete(agent_policies).where(
                agent_policies.c.namespace_key == namespace_key,
                agent_policies.c.agent_name == agent.name,
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to remove policy associations from agent '%s'",
            agent.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to remove policy associations from agent '{agent.name}': database error"
            ),
            resource="Agent",
            operation="remove policy",
        )

    return DeletePolicyResponse(success=True)


@router.post(
    "/{agent_name}/controls/{control_id}",
    response_model=AssocResponse,
    summary="Associate control directly with agent",
    response_description="Success confirmation",
)
async def add_agent_control(
    agent_name: str,
    control_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> AssocResponse:
    """Associate a control directly with an agent (idempotent)."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)
    control_service = ControlService(db)
    control = await control_service.get_active_control_or_404(
        control_id, namespace_key=namespace_key
    )

    validation_errors = _validate_controls_for_agent(agent, [control])
    if validation_errors:
        raise BadRequestError(
            error_code=ErrorCode.POLICY_CONTROL_INCOMPATIBLE,
            detail="Control is incompatible with this agent",
            hint="Ensure the control is compatible with this agent's rules.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field="rule",
                    code="incompatible",
                    message=err,
                )
                for err in validation_errors
            ],
        )

    try:
        await control_service.add_control_to_agent(
            agent_name=agent.name,
            control_id=control_id,
            namespace_key=namespace_key,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to associate control '%s' with agent '%s'",
            control_id,
            agent.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to associate control with agent '{agent.name}': database error",
            resource="Agent",
            operation="add control association",
        )

    return AssocResponse(success=True)


@router.delete(
    "/{agent_name}/controls/{control_id}",
    response_model=RemoveAgentControlResponse,
    summary="Remove direct control association from agent",
    response_description="Success confirmation",
)
async def remove_agent_control(
    agent_name: str,
    control_id: int,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> RemoveAgentControlResponse:
    """Remove a direct control association from an agent (idempotent)."""
    namespace_key = principal.namespace_key
    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)
    control_service = ControlService(db)
    await control_service.get_active_control_or_404(control_id, namespace_key=namespace_key)

    try:
        removal_result = await control_service.remove_control_from_agent(
            agent_name=agent.name,
            control_id=control_id,
            namespace_key=namespace_key,
        )

        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            "Failed to remove control '%s' from agent '%s'",
            control_id,
            agent.name,
            exc_info=True,
        )
        raise DatabaseError(
            detail=(
                f"Failed to remove control association from agent '{agent.name}': database error"
            ),
            resource="Agent",
            operation="remove control association",
        )

    return RemoveAgentControlResponse(
        success=True,
        removed_direct_association=removal_result.removed_direct_association,
        control_still_active=removal_result.control_still_active,
    )


@router.get(
    "/{agent_name}/controls",
    response_model=AgentControlsResponse,
    response_model_exclude_none=True,
    summary="List agent's associated controls",
    response_description=(
        "List of associated controls by default, including rendered, unrendered, "
        "enabled, and disabled controls"
    ),
)
async def list_agent_controls(
    agent_name: str,
    rendered_state: AgentControlRenderedState = Query(
        "all",
        description=(
            "Rendered-state filter. Default 'all' returns both rendered controls "
            "and unrendered template drafts."
        ),
    ),
    enabled_state: AgentControlEnabledState = Query(
        "all",
        description=(
            "Enabled-state filter. Default 'all' returns both enabled and disabled "
            "associated controls. Unrendered template drafts are disabled, so "
            "combine with rendered_state='rendered' to exclude them."
        ),
    ),
    target_type: str | None = Query(
        None,
        min_length=1,
        max_length=255,
        description=(
            "Optional opaque target kind. When supplied with target_id, the "
            "response includes controls bound to that target via enabled "
            "bindings, in addition to the agent's direct and policy-derived "
            "controls."
        ),
    ),
    target_id: str | None = Query(
        None,
        min_length=1,
        max_length=255,
        description="Optional opaque target identifier. Required when target_type is supplied.",
    ),
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_READ)),
    target_principal: Principal | None = Depends(_agent_controls_target_principal),
) -> AgentControlsResponse:
    """
    List protection controls effective for an agent.

    The effective set is the de-duplicated union of the agent's direct
    controls, policy-derived controls, and (when ``target_type`` and
    ``target_id`` are both supplied) controls attached to that target via
    enabled bindings in the same namespace. The same merge applies on
    ``initAgent`` and ``POST /evaluation`` so all three surfaces return the
    same set for the same inputs.

    By default, the endpoint returns all effective controls, including
    rendered controls, disabled controls, and unrendered template drafts.
    Callers can narrow the response via the state filters. Filters
    intersect, so unrendered drafts require rendered_state='unrendered'
    together with enabled_state='all' or 'disabled'.

    Args:
        agent_name: Agent identifier
        rendered_state: Whether to return rendered controls, unrendered drafts, or both
        enabled_state: Whether to return enabled controls, disabled controls, or both
        target_type: Optional opaque target kind (paired with target_id)
        target_id: Optional opaque target identifier (paired with target_type)
        db: Database session (injected)
        principal: Authorized request principal for the agent read operation
        target_principal: Optional principal from the target binding read check

    Returns:
        AgentControlsResponse with controls matching the requested state filters

    Raises:
        HTTPException 400: target_type and target_id were not supplied together
        HTTPException 404: Agent not found
    """
    namespace_key = principal.namespace_key
    _ensure_target_principal_matches_namespace(principal, target_principal)

    if (target_type is None) != (target_id is None):
        raise BadRequestError(
            error_code=ErrorCode.VALIDATION_ERROR,
            detail="target_type and target_id must be supplied together.",
            errors=[
                ValidationErrorItem(
                    resource="AgentControls",
                    field="target_type" if target_type is None else "target_id",
                    code="missing_target_pair",
                    message="target_type and target_id must be supplied together.",
                )
            ],
        )

    agent = await _get_agent_or_404(agent_name, db, namespace_key=namespace_key)
    controls = await ControlService(db).list_controls_for_agent(
        agent.name,
        namespace_key=namespace_key,
        target_type=target_type,
        target_id=target_id,
        rendered_state=rendered_state,
        enabled_state=enabled_state,
    )
    return AgentControlsResponse(controls=controls)


# =============================================================================
# Rule Schema Endpoints
# =============================================================================


class RuleSchemaItem(BaseModel):
    """Rule schema summary for list response."""

    name: str
    description: str | None
    config_schema: dict[str, Any]


class ListRulesResponse(BaseModel):
    """Response for listing agent's rule schemas."""

    rules: list[RuleSchemaItem]
    pagination: PaginationInfo


@router.get(
    "/{agent_name}/rules",
    response_model=ListRulesResponse,
    summary="List agent's registered rule schemas",
    response_description="Rule schemas registered with this agent",
)
async def list_agent_rules(
    agent_name: str,
    cursor: str | None = None,
    limit: int = _DEFAULT_PAGINATION_LIMIT,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_READ)),
) -> ListRulesResponse:
    """
    List all rule schemas registered with an agent.

    Rule schemas are registered via initAgent and used for:
    - Config validation when creating Controls
    - UI to display available config options

    Args:
        agent_name: Agent identifier
        cursor: Optional cursor for pagination (name of last rule from previous page)
        limit: Pagination limit (default 20, max 100)
        db: Database session (injected)
        principal: Authorized request principal

    Returns:
        ListRulesResponse with rule schemas and pagination

    Raises:
        HTTPException 404: Agent not found
    """
    namespace_key = principal.namespace_key
    agent_name = normalize_agent_name_or_422(agent_name)
    # Clamp limit
    limit = min(max(1, limit), _MAX_PAGINATION_LIMIT)

    result = await db.execute(
        select(Agent).where(Agent.name == agent_name, Agent.namespace_key == namespace_key)
    )
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with name '{agent_name}' not found",
            resource="Agent",
            resource_id=str(agent_name),
            hint="Verify the agent name is correct and the agent has been registered.",
        )

    try:
        data_model = AgentData.model_validate(agent.data)
    except ValidationError:
        data_model = AgentData(agent_metadata={}, steps=[], rules=[])

    all_rules = data_model.rules or []
    total = len(all_rules)

    # Apply cursor-based pagination
    # For rules, we use name as cursor (simple string comparison)
    start_idx = 0
    if cursor:
        # Find the index of the cursor rule
        for idx, rule in enumerate(all_rules):
            if rule.name == cursor:
                start_idx = idx + 1
                break

    # Fetch limit + 1 to check if there are more pages
    end_idx = start_idx + limit + 1
    paginated = all_rules[start_idx:end_idx]

    # Check if there are more pages
    has_more = len(paginated) > limit
    if has_more:
        paginated = paginated[:-1]  # Remove the extra item

    # Determine next cursor (name of last rule in this page)
    next_cursor: str | None = None
    if has_more and paginated:
        next_cursor = paginated[-1].name

    return ListRulesResponse(
        rules=[
            RuleSchemaItem(
                name=rule.name,
                description=rule.description,
                config_schema=rule.config_schema,
            )
            for rule in paginated
        ],
        pagination=PaginationInfo(
            limit=limit,
            total=total,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


@router.get(
    "/{agent_name}/rules/{rule_name}",
    response_model=RuleSchemaItem,
    summary="Get specific rule schema",
    response_description="Rule schema details",
)
async def get_agent_rule(
    agent_name: str,
    rule_name: str,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_READ)),
) -> RuleSchemaItem:
    """
    Get a specific rule schema registered with an agent.

    Args:
        agent_name: Agent identifier
        rule_name: Name of the rule
        db: Database session (injected)
        principal: Authorized request principal

    Returns:
        RuleSchemaItem with schema details

    Raises:
        HTTPException 404: Agent or rule not found
    """
    namespace_key = principal.namespace_key
    agent_name = normalize_agent_name_or_422(agent_name)
    result = await db.execute(
        select(Agent).where(Agent.name == agent_name, Agent.namespace_key == namespace_key)
    )
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with name '{agent_name}' not found",
            resource="Agent",
            resource_id=str(agent_name),
            hint="Verify the agent name is correct and the agent has been registered.",
        )

    try:
        data_model = AgentData.model_validate(agent.data)
    except ValidationError:
        raise NotFoundError(
            error_code=ErrorCode.RULE_NOT_FOUND,
            detail=f"Rule '{rule_name}' not found",
            resource="Rule",
            resource_id=rule_name,
            hint="The agent's data may be corrupted. Re-register the agent with initAgent.",
        )

    for rule in data_model.rules or []:
        if rule.name == rule_name:
            return RuleSchemaItem(
                name=rule.name,
                description=rule.description,
                config_schema=rule.config_schema,
            )

    raise NotFoundError(
        error_code=ErrorCode.RULE_NOT_FOUND,
        detail=f"Rule '{rule_name}' not found on agent '{agent.name}'",
        resource="Rule",
        resource_id=rule_name,
        hint="Register the rule with this agent via initAgent.",
    )


@router.patch(
    "/{agent_name}",
    response_model=PatchAgentResponse,
    summary="Modify agent (remove steps/rules)",
    response_description="Lists of removed items",
)
async def patch_agent(
    agent_name: str,
    request: PatchAgentRequest,
    db: AsyncSession = Depends(get_async_db),
    principal: Principal = Depends(require_operation(Operation.AGENTS_UPDATE)),
) -> PatchAgentResponse:
    """
    Remove steps and/or rules from an agent.

    This is the complement to initAgent which only adds items.
    Removals are idempotent - attempting to remove non-existent items is not an error.

    Args:
        agent_name: Agent identifier
        request: Lists of step/rule identifiers to remove
        db: Database session (injected)
        principal: Authorized request principal

    Returns:
        PatchAgentResponse with lists of actually removed items

    Raises:
        HTTPException 404: Agent not found
        HTTPException 500: Database error during update
    """
    namespace_key = principal.namespace_key
    agent_name = normalize_agent_name_or_422(agent_name)
    result = await db.execute(
        select(Agent).where(
            Agent.name == agent_name,
            Agent.namespace_key == namespace_key,
        )
    )
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with name '{agent_name}' not found",
            resource="Agent",
            resource_id=str(agent_name),
            hint="Verify the agent name is correct and the agent has been registered.",
        )

    try:
        data_model = AgentData.model_validate(agent.data)
    except ValidationError:
        raise APIValidationError(
            error_code=ErrorCode.CORRUPTED_DATA,
            detail=f"Agent '{agent.name}' has corrupted data",
            resource="Agent",
            hint="Re-register the agent with initAgent using force_replace=true.",
        )

    steps_removed: list[StepKey] = []
    rules_removed: list[str] = []

    # Remove steps
    if request.remove_steps:
        remove_step_set: set[StepKeyTuple] = {(s.type, s.name) for s in request.remove_steps}
        new_steps: list[StepSchema] = []
        for step in data_model.steps or []:
            key: StepKeyTuple = (step.type, step.name)
            if key in remove_step_set:
                steps_removed.append(StepKey(type=step.type, name=step.name))
            else:
                new_steps.append(step)
        data_model.steps = new_steps

    # Remove rules (with dependency check)
    if request.remove_rules:
        remove_rule_set = set(request.remove_rules)

        # Check if any active controls reference rules being removed.
        controls = await ControlService(db).list_controls_for_agent(
            agent.name,
            namespace_key=namespace_key,
        )
        referencing_controls = _find_referencing_controls_for_removed_rules(
            controls, agent.name, remove_rule_set
        )

        if referencing_controls:
            raise ConflictError(
                error_code=ErrorCode.RULE_IN_USE,
                detail="Cannot remove rules: active controls reference them",
                resource="Rule",
                hint="Remove or update the controls that reference these rules first.",
                errors=[
                    ValidationErrorItem(
                        resource="Control",
                        field="rule.name",
                        code="in_use",
                        message=f"Control '{ctrl}' uses rule '{rule}'",
                    )
                    for ctrl, rule in referencing_controls
                ],
            )

        new_rules = []
        for rule in data_model.rules or []:
            if rule.name in remove_rule_set:
                rules_removed.append(rule.name)
            else:
                new_rules.append(rule)
        data_model.rules = new_rules

    # Only update if something changed
    if steps_removed or rules_removed:
        agent.data = data_model.model_dump(mode="json")
        try:
            await db.commit()
            _logger.info(
                f"Patched agent '{agent.name}': removed {len(steps_removed)} steps, "
                f"{len(rules_removed)} rules"
            )
        except Exception:
            await db.rollback()
            _logger.error(
                f"Failed to patch agent '{agent.name}' ({agent_name})",
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to update agent '{agent.name}': database error",
                resource="Agent",
                operation="patch",
            )

    return PatchAgentResponse(
        steps_removed=steps_removed,
        rules_removed=rules_removed,
    )
