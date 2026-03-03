from typing import Any

from agent_control_engine import list_evaluators
from agent_control_models.agent import Agent as APIAgent
from agent_control_models.agent import StepSchema
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
    AgentControlsResponse,
    AgentSummary,
    AssocResponse,
    ConflictMode,
    DeletePolicyResponse,
    EvaluatorSchema,
    GetAgentPoliciesResponse,
    GetAgentResponse,
    GetPolicyResponse,
    InitAgentEvaluatorRemoval,
    InitAgentOverwriteChanges,
    InitAgentRequest,
    InitAgentResponse,
    ListAgentsResponse,
    PaginationInfo,
    PatchAgentRequest,
    PatchAgentResponse,
    RemoveAgentControlResponse,
    SetPolicyResponse,
    StepKey,
)
from fastapi import APIRouter, Depends
from jsonschema_rs import ValidationError as JSONSchemaValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_async_db
from ..errors import (
    APIValidationError,
    BadRequestError,
    ConflictError,
    DatabaseError,
    NotFoundError,
)
from ..logging_utils import get_logger
from ..models import (
    Agent,
    AgentData,
    Control,
    Policy,
    agent_controls,
    agent_policies,
    policy_controls,
)
from ..services.agent_names import normalize_agent_name_or_422
from ..services.controls import list_controls_for_agent, list_controls_for_policy
from ..services.evaluator_utils import (
    parse_evaluator_ref_full,
    validate_config_against_schema,
)
from ..services.query_utils import escape_like_pattern
from ..services.schema_compat import (
    check_schema_compatibility,
    format_compatibility_error,
)

router = APIRouter(prefix="/agents", tags=["agents"])

_logger = get_logger(__name__)

# Cache for built-in evaluator names (populated on first use)
_BUILTIN_EVALUATOR_NAMES: set[str] | None = None

# Pagination constants
_DEFAULT_PAGINATION_OFFSET = 0
_DEFAULT_PAGINATION_LIMIT = 20
_MAX_PAGINATION_LIMIT = 100
_CORRUPTED_AGENT_DATA_MESSAGE = "Stored agent data is corrupted and cannot be parsed."

type StepKeyTuple = tuple[str, str]


# =============================================================================
# List Agents Models
# =============================================================================


def _get_builtin_evaluator_names() -> set[str]:
    """Get built-in evaluator names (cached)."""
    global _BUILTIN_EVALUATOR_NAMES
    if _BUILTIN_EVALUATOR_NAMES is None:
        _BUILTIN_EVALUATOR_NAMES = set(list_evaluators().keys())
    return _BUILTIN_EVALUATOR_NAMES


def _validate_controls_for_agent(agent: Agent, controls: list[Control]) -> list[str]:
    """Validate controls can run on this agent."""
    errors: list[str] = []

    # Parse agent's registered evaluators
    try:
        agent_data = AgentData.model_validate(agent.data)
    except ValidationError:
        return [f"Agent '{agent.name}' has corrupted data"]

    agent_evaluators = {e.name: e for e in (agent_data.evaluators or [])}

    for control in controls:
        if not control.data:
            continue

        evaluator_cfg = control.data.get("evaluator", {})
        evaluator_name = evaluator_cfg.get("name", "")
        if not evaluator_name:
            continue

        parsed = parse_evaluator_ref_full(evaluator_name)
        if parsed.type != "agent":
            continue  # Built-in/external evaluator, already validated at control creation

        # Agent-scoped evaluator - check if target matches this agent
        if parsed.namespace != agent.name:
            errors.append(
                f"Control '{control.name}' references evaluator '{evaluator_name}' "
                f"which belongs to agent '{parsed.namespace}', not '{agent.name}'"
            )
            continue

        # Check if evaluator exists on this agent
        if parsed.local_name not in agent_evaluators:
            errors.append(
                f"Control '{control.name}' references evaluator '{parsed.local_name}' "
                f"which is not registered with agent '{agent.name}'. "
                f"Register it via initAgent or use a different evaluator."
            )
            continue

        # Validate config against schema
        registered_ev = agent_evaluators[parsed.local_name]
        config = evaluator_cfg.get("config", {})
        if registered_ev.config_schema:
            try:
                validate_config_against_schema(config, registered_ev.config_schema)
            except JSONSchemaValidationError as e:
                errors.append(
                    f"Control '{control.name}' invalid config for "
                    f"'{parsed.local_name}': {e.message}"
                )

    return errors


async def _validate_policy_controls_for_agent(
    agent: Agent, policy_id: int, db: AsyncSession
) -> list[str]:
    """Validate all controls in a policy can run on this agent."""
    controls = await list_controls_for_policy(policy_id, db)
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


async def _build_overwrite_evaluator_removals(
    agent: Agent,
    removed_evaluators: set[str],
    db: AsyncSession,
) -> list[InitAgentEvaluatorRemoval]:
    """Build evaluator removal details, including active-control references."""
    if not removed_evaluators:
        return []

    try:
        controls = await list_controls_for_agent(
            agent.name,
            db,
            allow_invalid_step_name_regex=True,
        )
    except APIValidationError:
        _logger.warning(
            "Skipping evaluator removal reference checks for agent '%s' "
            "due to invalid control data",
            agent.name,
            exc_info=True,
        )
        return [InitAgentEvaluatorRemoval(name=name) for name in sorted(removed_evaluators)]

    references_by_evaluator: dict[str, list[tuple[int, str]]] = {}
    for control in controls:
        evaluator_ref = control.control.evaluator.name
        parsed = parse_evaluator_ref_full(evaluator_ref)
        if parsed.type != "agent":
            continue
        if parsed.namespace != agent.name:
            continue
        if parsed.local_name not in removed_evaluators:
            continue
        references_by_evaluator.setdefault(parsed.local_name, []).append((control.id, control.name))

    removals: list[InitAgentEvaluatorRemoval] = []
    for evaluator_name in sorted(removed_evaluators):
        references = references_by_evaluator.get(evaluator_name)
        if references is None:
            removals.append(InitAgentEvaluatorRemoval(name=evaluator_name))
            continue
        removals.append(
            InitAgentEvaluatorRemoval(
                name=evaluator_name,
                referenced_by_active_controls=True,
                control_ids=[control_id for control_id, _ in references],
                control_names=[control_name for _, control_name in references],
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
) -> ListAgentsResponse:
    """
    List all registered agents with cursor-based pagination.

    Returns a summary of each agent including identifier, policy associations,
    and counts of registered steps and evaluators.

    Args:
        cursor: Optional cursor for pagination (last agent name from previous page)
        limit: Pagination limit (default 20, max 100)
        name: Optional name filter (case-insensitive partial match)
        db: Database session (injected)

    Returns:
        ListAgentsResponse with agent summaries and pagination info
    """
    # Clamp limit
    limit = min(max(1, limit), _MAX_PAGINATION_LIMIT)

    # Build base filter for name search
    name_filter = (
        Agent.name.ilike(f"%{escape_like_pattern(name)}%", escape="\\") if name else None
    )

    # Get total count (with name filter if provided)
    count_query = select(func.count()).select_from(Agent)
    if name_filter is not None:
        count_query = count_query.where(name_filter)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Build query with cursor-based pagination
    # Order by created_at DESC, then by name DESC for stable ordering
    query = select(Agent).order_by(Agent.created_at.desc(), Agent.name.desc())

    # Apply name filter if provided
    if name_filter is not None:
        query = query.where(name_filter)

    # If cursor provided, filter to get items after the cursor
    if cursor:
        cursor_name = normalize_agent_name_or_422(cursor, field_name="cursor")
        cursor_agent_result = await db.execute(
            select(Agent).where(Agent.name == cursor_name)
        )
        cursor_agent = cursor_agent_result.scalars().first()
        if cursor_agent:
            query = query.where(
                (Agent.created_at < cursor_agent.created_at)
                | (
                    (Agent.created_at == cursor_agent.created_at)
                    & (Agent.name < cursor_agent.name)
                )
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
    if agents:
        agent_names = [agent.name for agent in agents]

        policy_ids_query = (
            select(
                agent_policies.c.agent_name,
                agent_policies.c.policy_id,
            )
            .where(agent_policies.c.agent_name.in_(agent_names))
            .order_by(agent_policies.c.agent_name, agent_policies.c.policy_id)
        )
        policy_ids_result = await db.execute(policy_ids_query)
        for assoc_agent_name, policy_id in policy_ids_result.all():
            policy_ids_map.setdefault(assoc_agent_name, []).append(policy_id)

        policy_associations = (
            select(
                agent_policies.c.agent_name.label("agent_name"),
                policy_controls.c.control_id.label("control_id"),
            )
            .select_from(
                agent_policies.join(
                    policy_controls, agent_policies.c.policy_id == policy_controls.c.policy_id
                )
            )
            .where(agent_policies.c.agent_name.in_(agent_names))
        )
        direct_associations = select(
            agent_controls.c.agent_name.label("agent_name"),
            agent_controls.c.control_id.label("control_id"),
        ).where(agent_controls.c.agent_name.in_(agent_names))
        all_associations = union_all(policy_associations, direct_associations).subquery()

        control_counts_query = (
            select(
                all_associations.c.agent_name,
                func.count(func.distinct(all_associations.c.control_id)).label("count"),
            )
            .join(Control, all_associations.c.control_id == Control.id)
            .where(
                or_(
                    Control.data["enabled"].astext == "true",
                    ~Control.data.has_key("enabled"),
                ),
            )
            .group_by(all_associations.c.agent_name)
        )
        control_counts_result = await db.execute(control_counts_query)
        control_counts_map = {row[0]: row[1] for row in control_counts_result.all()}

    # Build summaries
    summaries: list[AgentSummary] = []
    for agent in agents:
        step_count = 0
        evaluator_count = 0

        # Parse agent data to get counts
        try:
            data_model = AgentData.model_validate(agent.data)
            step_count = len(data_model.steps or [])
            evaluator_count = len(data_model.evaluators or [])
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
                evaluator_count=evaluator_count,
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
    request: InitAgentRequest, db: AsyncSession = Depends(get_async_db)
) -> InitAgentResponse:
    """
    Register a new agent or update an existing agent's steps and metadata.

    This endpoint is idempotent:
    - If the agent name doesn't exist, creates a new agent
    - If the agent name exists, updates registration data in place

    conflict_mode controls registration conflict handling:
    - strict (default): preserve compatibility checks and conflict errors
    - overwrite: latest init payload replaces steps/evaluators and returns change summary

    Args:
        request: Agent metadata and step schemas
        db: Database session (injected)

    Returns:
        InitAgentResponse with created flag and active controls (policy-derived + direct)
    """
    # Check for evaluator name collisions with built-in evaluators
    builtin_names = _get_builtin_evaluator_names()
    for ev in request.evaluators:
        if ev.name in builtin_names:
            raise ConflictError(
                error_code=ErrorCode.EVALUATOR_NAME_CONFLICT,
                detail=f"Evaluator name '{ev.name}' conflicts with built-in evaluator.",
                resource="Evaluator",
                resource_id=ev.name,
                hint="Choose a different name that does not conflict with built-in evaluators.",
                errors=[
                    ValidationErrorItem(
                        resource="Evaluator",
                        field="name",
                        code="name_conflict",
                        message=f"Name '{ev.name}' conflicts with a built-in evaluator",
                        value=ev.name,
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

    result = await db.execute(select(Agent).where(Agent.name == request.agent.agent_name))
    existing: Agent | None = result.scalars().first()

    created = False

    if existing is None:
        created = True

        data_model = AgentData(
            agent_metadata=request.agent.model_dump(mode="json"),
            steps=list(request.steps),
            evaluators=list(request.evaluators),
        )

        new_agent = Agent(
            name=request.agent.agent_name,
            data=data_model.model_dump(mode="json"),
        )
        db.add(new_agent)
        try:
            await db.commit()
            _logger.info(
                f"Created agent '{request.agent.agent_name}' with {len(request.steps)} steps, "
                f"{len(request.evaluators)} evaluators"
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
        return InitAgentResponse(created=created, controls=[])

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
        data_model = AgentData(agent_metadata={}, steps=[], evaluators=[])

    steps_changed = False
    evaluators_changed = False
    force_write = request.force_replace  # Always persist when force_replace=true
    overwrite_applied = False
    overwrite_changes = InitAgentOverwriteChanges()

    # --- Update agent metadata ---
    new_metadata = request.agent.model_dump(mode="json")
    metadata_changed = data_model.agent_metadata != new_metadata
    if metadata_changed:
        data_model.agent_metadata = new_metadata

    new_steps: list[StepSchema]
    new_evaluators: list[EvaluatorSchema]

    if request.conflict_mode == ConflictMode.OVERWRITE:
        # Latest-init-wins: overwrite steps/evaluators exactly with incoming payload.
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

        existing_evaluators = list(data_model.evaluators or [])
        existing_evals_by_name: dict[str, EvaluatorSchema] = {
            evaluator.name: evaluator for evaluator in existing_evaluators
        }
        incoming_evals_by_name: dict[str, EvaluatorSchema] = {
            evaluator.name: evaluator for evaluator in request.evaluators
        }
        existing_eval_names = set(existing_evals_by_name)
        incoming_eval_names = set(incoming_evals_by_name)

        evaluators_added_names = sorted(incoming_eval_names - existing_eval_names)
        evaluators_removed_names = sorted(existing_eval_names - incoming_eval_names)
        evaluators_updated_names = sorted(
            name
            for name in (existing_eval_names & incoming_eval_names)
            if (
                existing_evals_by_name[name].config_schema
                != incoming_evals_by_name[name].config_schema
                or existing_evals_by_name[name].description
                != incoming_evals_by_name[name].description
            )
        )

        evaluator_removals: list[InitAgentEvaluatorRemoval] = []
        if evaluators_removed_names:
            evaluator_removals = await _build_overwrite_evaluator_removals(
                existing,
                set(evaluators_removed_names),
                db,
            )

        overwrite_changes = InitAgentOverwriteChanges(
            metadata_changed=metadata_changed,
            steps_added=[_step_key_model(step_key) for step_key in steps_added_keys],
            steps_updated=[_step_key_model(step_key) for step_key in steps_updated_keys],
            steps_removed=[_step_key_model(step_key) for step_key in steps_removed_keys],
            evaluators_added=evaluators_added_names,
            evaluators_updated=evaluators_updated_names,
            evaluators_removed=evaluators_removed_names,
            evaluator_removals=evaluator_removals,
        )

        steps_changed = bool(steps_added_keys or steps_updated_keys or steps_removed_keys)
        evaluators_changed = bool(
            evaluators_added_names or evaluators_updated_names or evaluators_removed_names
        )
        overwrite_applied = bool(metadata_changed or steps_changed or evaluators_changed)

        new_steps = list(request.steps)
        new_evaluators = list(request.evaluators)
        data_model.steps = new_steps
        data_model.evaluators = new_evaluators
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

        # --- Process evaluators with schema compatibility check ---
        incoming_evals_by_name = {evaluator.name: evaluator for evaluator in request.evaluators}
        existing_evals_by_name = {
            evaluator.name: evaluator for evaluator in (data_model.evaluators or [])
        }
        new_evaluators = []

        # Check existing evaluators for compatibility
        for name, existing_ev in existing_evals_by_name.items():
            if name in incoming_evals_by_name:
                incoming_ev = incoming_evals_by_name[name]
                old_schema = existing_ev.config_schema
                new_schema = incoming_ev.config_schema

                # Short-circuit: only check compatibility if schemas differ
                if old_schema != new_schema:
                    is_compatible, compat_errors = check_schema_compatibility(
                        old_schema, new_schema
                    )
                    if not is_compatible:
                        raise ConflictError(
                            error_code=ErrorCode.SCHEMA_INCOMPATIBLE,
                            detail=format_compatibility_error(name, compat_errors),
                            resource="Evaluator",
                            resource_id=name,
                            hint="Ensure backward compatibility or use a new evaluator name.",
                            errors=[
                                ValidationErrorItem(
                                    resource="Evaluator",
                                    field="config_schema",
                                    code="schema_incompatible",
                                    message=err,
                                )
                                for err in compat_errors
                            ],
                        )

                # Check if evaluator changed (compare fields directly, avoid model_dump())
                if (
                    existing_ev.config_schema != incoming_ev.config_schema
                    or existing_ev.description != incoming_ev.description
                ):
                    evaluators_changed = True
                new_evaluators.append(incoming_ev)
            else:
                # Keep existing evaluator not in incoming request
                new_evaluators.append(existing_ev)

        # Add new evaluators
        for name, evaluator in incoming_evals_by_name.items():
            if name not in existing_evals_by_name:
                new_evaluators.append(evaluator)
                evaluators_changed = True

        data_model.evaluators = new_evaluators

    if steps_changed or evaluators_changed or metadata_changed or force_write:
        existing.data = data_model.model_dump(mode="json")

        try:
            await db.commit()
            _logger.info(
                f"Updated agent '{request.agent.agent_name}' with {len(new_steps)} steps, "
                f"{len(new_evaluators)} evaluators"
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

    controls = await list_controls_for_agent(existing.name, db)

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
async def get_agent(agent_name: str, db: AsyncSession = Depends(get_async_db)) -> GetAgentResponse:
    """
    Retrieve agent metadata and all registered steps.

    Returns the latest version of each step (deduplicated by type+name).

    Args:
        agent_name: Agent identifier
        db: Database session (injected)

    Returns:
        GetAgentResponse with agent metadata and step list

    Raises:
        HTTPException 404: Agent not found
        HTTPException 422: Agent data is corrupted
    """
    agent_name = normalize_agent_name_or_422(agent_name)
    result = await db.execute(select(Agent).where(Agent.name == agent_name))
    existing: Agent | None = result.scalars().first()
    if existing is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with name '{agent_name}' not found",
            resource="Agent",
            resource_id=str(agent_name),
            hint=(
                "Verify the agent name is correct and the agent has been "
                "registered via initAgent."
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

    return GetAgentResponse(
        agent=agent_meta, steps=latest_steps, evaluators=data_model.evaluators
    )


async def _get_agent_or_404(agent_name: str, db: AsyncSession) -> Agent:
    """Get an agent or raise AGENT_NOT_FOUND."""
    normalized_agent_name = normalize_agent_name_or_422(agent_name)
    result = await db.execute(select(Agent).where(Agent.name == normalized_agent_name))
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
    agent_name: str, policy_id: int, db: AsyncSession = Depends(get_async_db)
) -> AssocResponse:
    """Associate a policy with an agent (idempotent)."""
    agent = await _get_agent_or_404(agent_name, db)

    policy_result = await db.execute(select(Policy).where(Policy.id == policy_id))
    policy: Policy | None = policy_result.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    validation_errors = await _validate_policy_controls_for_agent(agent, policy_id, db)
    if validation_errors:
        raise BadRequestError(
            error_code=ErrorCode.POLICY_CONTROL_INCOMPATIBLE,
            detail="Policy contains controls incompatible with this agent",
            hint="Ensure all controls in the policy are compatible with this agent's evaluators.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field="evaluator",
                    code="incompatible",
                    message=err,
                )
                for err in validation_errors
            ],
        )

    try:
        stmt = (
            pg_insert(agent_policies)
            .values(agent_name=agent.name, policy_id=policy_id)
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
    agent_name: str, policy_id: int, db: AsyncSession = Depends(get_async_db)
) -> SetPolicyResponse:
    """Compatibility endpoint that replaces all policy associations with one policy."""
    agent = await _get_agent_or_404(agent_name, db)

    policy_result = await db.execute(select(Policy).where(Policy.id == policy_id))
    policy: Policy | None = policy_result.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Policy with ID '{policy_id}' not found",
            resource="Policy",
            resource_id=str(policy_id),
            hint="Verify the policy ID is correct and the policy has been created.",
        )

    validation_errors = await _validate_policy_controls_for_agent(agent, policy_id, db)
    if validation_errors:
        raise BadRequestError(
            error_code=ErrorCode.POLICY_CONTROL_INCOMPATIBLE,
            detail="Policy contains controls incompatible with this agent",
            hint="Ensure all controls in the policy are compatible with this agent's evaluators.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field="evaluator",
                    code="incompatible",
                    message=err,
                )
                for err in validation_errors
            ],
        )

    existing_policies_result = await db.execute(
        select(agent_policies.c.policy_id)
        .where(agent_policies.c.agent_name == agent.name)
        .order_by(agent_policies.c.policy_id)
    )
    existing_policy_ids = [row[0] for row in existing_policies_result.all()]
    old_policy_id = existing_policy_ids[0] if existing_policy_ids else None

    try:
        await db.execute(delete(agent_policies).where(agent_policies.c.agent_name == agent.name))
        await db.execute(
            pg_insert(agent_policies)
            .values(agent_name=agent.name, policy_id=policy_id)
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
    agent_name: str, db: AsyncSession = Depends(get_async_db)
) -> GetAgentPoliciesResponse:
    """List policy IDs associated with an agent."""
    agent = await _get_agent_or_404(agent_name, db)
    result = await db.execute(
        select(agent_policies.c.policy_id)
        .where(agent_policies.c.agent_name == agent.name)
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
    agent_name: str, db: AsyncSession = Depends(get_async_db)
) -> GetPolicyResponse:
    """Compatibility endpoint that returns the first associated policy."""
    agent = await _get_agent_or_404(agent_name, db)
    policy_result = await db.execute(
        select(Policy.id)
        .join(agent_policies, agent_policies.c.policy_id == Policy.id)
        .where(agent_policies.c.agent_name == agent.name)
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
    agent_name: str, policy_id: int, db: AsyncSession = Depends(get_async_db)
) -> AssocResponse:
    """Remove a policy association from an agent.

    Idempotent for existing resources: removing a non-associated link is a no-op.
    Missing agent/policy resources still return 404.
    """
    agent = await _get_agent_or_404(agent_name, db)

    policy_result = await db.execute(select(Policy.id).where(Policy.id == policy_id))
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
                (agent_policies.c.agent_name == agent.name)
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
    agent_name: str, db: AsyncSession = Depends(get_async_db)
) -> AssocResponse:
    """Remove all policy associations from an agent."""
    agent = await _get_agent_or_404(agent_name, db)

    try:
        await db.execute(delete(agent_policies).where(agent_policies.c.agent_name == agent.name))
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
                f"Failed to remove policy associations from agent '{agent.name}': "
                "database error"
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
    agent_name: str, db: AsyncSession = Depends(get_async_db)
) -> DeletePolicyResponse:
    """Compatibility endpoint that removes all policy associations."""
    agent = await _get_agent_or_404(agent_name, db)

    existing_policy_result = await db.execute(
        select(agent_policies.c.policy_id)
        .where(agent_policies.c.agent_name == agent.name)
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
        await db.execute(delete(agent_policies).where(agent_policies.c.agent_name == agent.name))
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
                f"Failed to remove policy associations from agent '{agent.name}': "
                "database error"
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
    agent_name: str, control_id: int, db: AsyncSession = Depends(get_async_db)
) -> AssocResponse:
    """Associate a control directly with an agent (idempotent)."""
    agent = await _get_agent_or_404(agent_name, db)

    control_result = await db.execute(select(Control).where(Control.id == control_id))
    control: Control | None = control_result.scalars().first()
    if control is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )

    validation_errors = _validate_controls_for_agent(agent, [control])
    if validation_errors:
        raise BadRequestError(
            error_code=ErrorCode.POLICY_CONTROL_INCOMPATIBLE,
            detail="Control is incompatible with this agent",
            hint="Ensure the control is compatible with this agent's evaluators.",
            errors=[
                ValidationErrorItem(
                    resource="Control",
                    field="evaluator",
                    code="incompatible",
                    message=err,
                )
                for err in validation_errors
            ],
        )

    try:
        stmt = (
            pg_insert(agent_controls)
            .values(agent_name=agent.name, control_id=control_id)
            .on_conflict_do_nothing()
        )
        await db.execute(stmt)
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
    agent_name: str, control_id: int, db: AsyncSession = Depends(get_async_db)
) -> RemoveAgentControlResponse:
    """Remove a direct control association from an agent (idempotent)."""
    agent = await _get_agent_or_404(agent_name, db)

    control_result = await db.execute(select(Control.id).where(Control.id == control_id))
    if control_result.first() is None:
        raise NotFoundError(
            error_code=ErrorCode.CONTROL_NOT_FOUND,
            detail=f"Control with ID '{control_id}' not found",
            resource="Control",
            resource_id=str(control_id),
            hint="Verify the control ID is correct and the control has been created.",
        )

    try:
        remove_direct_stmt = (
            delete(agent_controls)
            .where(
                (agent_controls.c.agent_name == agent.name)
                & (agent_controls.c.control_id == control_id)
            )
            .returning(agent_controls.c.control_id)
        )
        remove_direct_result = await db.execute(remove_direct_stmt)
        removed_direct_association = remove_direct_result.first() is not None

        # The control may still be active for this agent if inherited from policy association(s).
        policy_inheritance_result = await db.execute(
            select(policy_controls.c.control_id)
            .select_from(
                agent_policies.join(
                    policy_controls,
                    agent_policies.c.policy_id == policy_controls.c.policy_id,
                )
            )
            .where(
                (agent_policies.c.agent_name == agent.name)
                & (policy_controls.c.control_id == control_id)
            )
            .limit(1)
        )
        control_still_active = policy_inheritance_result.first() is not None

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
                f"Failed to remove control association from agent '{agent.name}': "
                "database error"
            ),
            resource="Agent",
            operation="remove control association",
        )

    return RemoveAgentControlResponse(
        success=True,
        removed_direct_association=removed_direct_association,
        control_still_active=control_still_active,
    )


@router.get(
    "/{agent_name}/controls",
    response_model=AgentControlsResponse,
    summary="List agent's active controls",
    response_description="List of controls from agent policy and direct associations",
)
async def list_agent_controls(
    agent_name: str, db: AsyncSession = Depends(get_async_db)
) -> AgentControlsResponse:
    """
    List all protection controls active for an agent.

    Controls include the union of policy-derived and directly associated controls.

    Args:
        agent_name: Agent identifier
        db: Database session (injected)

    Returns:
        AgentControlsResponse with list of active controls

    Raises:
        HTTPException 404: Agent not found
    """
    agent = await _get_agent_or_404(agent_name, db)
    controls = await list_controls_for_agent(agent.name, db)
    return AgentControlsResponse(controls=controls)


# =============================================================================
# Evaluator Schema Endpoints
# =============================================================================


class EvaluatorSchemaItem(BaseModel):
    """Evaluator schema summary for list response."""

    name: str
    description: str | None
    config_schema: dict[str, Any]




class ListEvaluatorsResponse(BaseModel):
    """Response for listing agent's evaluator schemas."""

    evaluators: list[EvaluatorSchemaItem]
    pagination: PaginationInfo


@router.get(
    "/{agent_name}/evaluators",
    response_model=ListEvaluatorsResponse,
    summary="List agent's registered evaluator schemas",
    response_description="Evaluator schemas registered with this agent",
)
async def list_agent_evaluators(
    agent_name: str,
    cursor: str | None = None,
    limit: int = _DEFAULT_PAGINATION_LIMIT,
    db: AsyncSession = Depends(get_async_db),
) -> ListEvaluatorsResponse:
    """
    List all evaluator schemas registered with an agent.

    Evaluator schemas are registered via initAgent and used for:
    - Config validation when creating Controls
    - UI to display available config options

    Args:
        agent_name: Agent identifier
        cursor: Optional cursor for pagination (name of last evaluator from previous page)
        limit: Pagination limit (default 20, max 100)
        db: Database session (injected)

    Returns:
        ListEvaluatorsResponse with evaluator schemas and pagination

    Raises:
        HTTPException 404: Agent not found
    """
    agent_name = normalize_agent_name_or_422(agent_name)
    # Clamp limit
    limit = min(max(1, limit), _MAX_PAGINATION_LIMIT)

    result = await db.execute(select(Agent).where(Agent.name == agent_name))
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
        data_model = AgentData(agent_metadata={}, steps=[], evaluators=[])

    all_evaluators = data_model.evaluators or []
    total = len(all_evaluators)

    # Apply cursor-based pagination
    # For evaluators, we use name as cursor (simple string comparison)
    start_idx = 0
    if cursor:
        # Find the index of the cursor evaluator
        for idx, ev in enumerate(all_evaluators):
            if ev.name == cursor:
                start_idx = idx + 1
                break

    # Fetch limit + 1 to check if there are more pages
    end_idx = start_idx + limit + 1
    paginated = all_evaluators[start_idx:end_idx]

    # Check if there are more pages
    has_more = len(paginated) > limit
    if has_more:
        paginated = paginated[:-1]  # Remove the extra item

    # Determine next cursor (name of last evaluator in this page)
    next_cursor: str | None = None
    if has_more and paginated:
        next_cursor = paginated[-1].name

    return ListEvaluatorsResponse(
        evaluators=[
            EvaluatorSchemaItem(
                name=ev.name,
                description=ev.description,
                config_schema=ev.config_schema,
            )
            for ev in paginated
        ],
        pagination=PaginationInfo(
            limit=limit,
            total=total,
            next_cursor=next_cursor,
            has_more=has_more,
        ),
    )


@router.get(
    "/{agent_name}/evaluators/{evaluator_name}",
    response_model=EvaluatorSchemaItem,
    summary="Get specific evaluator schema",
    response_description="Evaluator schema details",
)
async def get_agent_evaluator(
    agent_name: str,
    evaluator_name: str,
    db: AsyncSession = Depends(get_async_db),
) -> EvaluatorSchemaItem:
    """
    Get a specific evaluator schema registered with an agent.

    Args:
        agent_name: Agent identifier
        evaluator_name: Name of the evaluator
        db: Database session (injected)

    Returns:
        EvaluatorSchemaItem with schema details

    Raises:
        HTTPException 404: Agent or evaluator not found
    """
    agent_name = normalize_agent_name_or_422(agent_name)
    result = await db.execute(select(Agent).where(Agent.name == agent_name))
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
            error_code=ErrorCode.EVALUATOR_NOT_FOUND,
            detail=f"Evaluator '{evaluator_name}' not found",
            resource="Evaluator",
            resource_id=evaluator_name,
            hint="The agent's data may be corrupted. Re-register the agent with initAgent.",
        )

    for ev in data_model.evaluators or []:
        if ev.name == evaluator_name:
            return EvaluatorSchemaItem(
                name=ev.name,
                description=ev.description,
                config_schema=ev.config_schema,
            )

    raise NotFoundError(
        error_code=ErrorCode.EVALUATOR_NOT_FOUND,
        detail=f"Evaluator '{evaluator_name}' not found on agent '{agent.name}'",
        resource="Evaluator",
        resource_id=evaluator_name,
        hint="Register the evaluator with this agent via initAgent.",
    )


@router.patch(
    "/{agent_name}",
    response_model=PatchAgentResponse,
    summary="Modify agent (remove steps/evaluators)",
    response_description="Lists of removed items",
)
async def patch_agent(
    agent_name: str,
    request: PatchAgentRequest,
    db: AsyncSession = Depends(get_async_db),
) -> PatchAgentResponse:
    """
    Remove steps and/or evaluators from an agent.

    This is the complement to initAgent which only adds items.
    Removals are idempotent - attempting to remove non-existent items is not an error.

    Args:
        agent_name: Agent identifier
        request: Lists of step/evaluator identifiers to remove
        db: Database session (injected)

    Returns:
        PatchAgentResponse with lists of actually removed items

    Raises:
        HTTPException 404: Agent not found
        HTTPException 500: Database error during update
    """
    agent_name = normalize_agent_name_or_422(agent_name)
    result = await db.execute(select(Agent).where(Agent.name == agent_name))
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
    evaluators_removed: list[str] = []

    # Remove steps
    if request.remove_steps:
        remove_step_set: set[StepKeyTuple] = {
            (s.type, s.name) for s in request.remove_steps
        }
        new_steps: list[StepSchema] = []
        for step in data_model.steps or []:
            key: StepKeyTuple = (step.type, step.name)
            if key in remove_step_set:
                steps_removed.append(StepKey(type=step.type, name=step.name))
            else:
                new_steps.append(step)
        data_model.steps = new_steps

    # Remove evaluators (with dependency check)
    if request.remove_evaluators:
        remove_evaluator_set = set(request.remove_evaluators)

        # Check if any active controls reference evaluators being removed.
        controls = await list_controls_for_agent(agent.name, db)
        referencing_controls: list[tuple[str, str]] = []  # (control_name, evaluator)

        for ctrl in controls:
            evaluator_ref = ctrl.control.evaluator.name
            if ":" in evaluator_ref:
                ref_agent, ref_eval = evaluator_ref.split(":", 1)
                # Check if this control references an evaluator we're removing
                # AND it's scoped to this agent (by name match)
                if ref_agent == agent.name and ref_eval in remove_evaluator_set:
                    referencing_controls.append((ctrl.name, ref_eval))

        if referencing_controls:
            raise ConflictError(
                error_code=ErrorCode.EVALUATOR_IN_USE,
                detail="Cannot remove evaluators: active controls reference them",
                resource="Evaluator",
                hint="Remove or update the controls that reference these evaluators first.",
                errors=[
                    ValidationErrorItem(
                        resource="Control",
                        field="evaluator.name",
                        code="in_use",
                        message=f"Control '{ctrl}' uses evaluator '{ev}'",
                    )
                    for ctrl, ev in referencing_controls
                ],
            )

        new_evaluators = []
        for ev in data_model.evaluators or []:
            if ev.name in remove_evaluator_set:
                evaluators_removed.append(ev.name)
            else:
                new_evaluators.append(ev)
        data_model.evaluators = new_evaluators

    # Only update if something changed
    if steps_removed or evaluators_removed:
        agent.data = data_model.model_dump(mode="json")
        try:
            await db.commit()
            _logger.info(
                f"Patched agent '{agent.name}': removed {len(steps_removed)} steps, "
                f"{len(evaluators_removed)} evaluators"
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
        evaluators_removed=evaluators_removed,
    )
