from typing import Any
from uuid import UUID

from agent_control_engine import list_evaluators
from agent_control_models.agent import Agent as APIAgent
from agent_control_models.agent import StepSchema
from agent_control_models.errors import ErrorCode, ValidationErrorItem
from agent_control_models.server import (
    AgentControlsResponse,
    AgentSummary,
    ConflictMode,
    DeletePolicyResponse,
    EvaluatorSchema,
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
    SetPolicyResponse,
    StepKey,
)
from fastapi import APIRouter, Depends
from jsonschema_rs import ValidationError as JSONSchemaValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
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
    policy_controls,
)
from ..services.controls import list_controls_for_agent, list_controls_for_policy
from ..services.evaluator_utils import (
    parse_evaluator_ref_full,
    validate_config_against_schema,
)
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


async def _validate_policy_controls_for_agent(
    agent: Agent, policy_id: int, db: AsyncSession
) -> list[str]:
    """Validate all controls in a policy can run on this agent.

    Checks that agent-scoped evaluators referenced by controls:
    1. Exist on the agent (registered via initAgent)
    2. Have config that validates against the evaluator's schema

    Returns:
        List of error messages (empty if all valid)
    """
    errors: list[str] = []

    # Parse agent's registered evaluators
    try:
        agent_data = AgentData.model_validate(agent.data)
    except ValidationError:
        return [f"Agent '{agent.name}' has corrupted data"]

    agent_evaluators = {e.name: e for e in (agent_data.evaluators or [])}

    # Get all controls for this policy
    controls = await list_controls_for_policy(policy_id, db)

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
    if not removed_evaluators or agent.policy_id is None:
        return [InitAgentEvaluatorRemoval(name=name) for name in sorted(removed_evaluators)]

    try:
        controls = await list_controls_for_agent(
            agent.agent_uuid,
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

    Returns a summary of each agent including ID, name, policy assignment,
    and counts of registered steps and evaluators.

    Args:
        cursor: Optional cursor for pagination (UUID of last agent from previous page)
        limit: Pagination limit (default 20, max 100)
        name: Optional name filter (case-insensitive partial match)
        db: Database session (injected)

    Returns:
        ListAgentsResponse with agent summaries and pagination info
    """
    # Clamp limit
    limit = min(max(1, limit), _MAX_PAGINATION_LIMIT)

    # Build base filter for name search
    name_filter = Agent.name.ilike(f"%{name}%") if name else None

    # Get total count (with name filter if provided)
    count_query = select(func.count()).select_from(Agent)
    if name_filter is not None:
        count_query = count_query.where(name_filter)
    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Build query with cursor-based pagination
    # Order by created_at DESC, then by UUID DESC for stable ordering
    query = select(Agent).order_by(Agent.created_at.desc(), Agent.agent_uuid.desc())

    # Apply name filter if provided
    if name_filter is not None:
        query = query.where(name_filter)

    # If cursor provided, filter to get items after the cursor
    if cursor:
        try:
            cursor_uuid = UUID(cursor)
            # Get the cursor agent to find its created_at timestamp
            cursor_agent_result = await db.execute(
                select(Agent).where(Agent.agent_uuid == cursor_uuid)
            )
            cursor_agent = cursor_agent_result.scalars().first()
            if cursor_agent:
                # Get agents created before this one (or same timestamp but smaller UUID)
                query = query.where(
                    (Agent.created_at < cursor_agent.created_at)
                    | (
                        (Agent.created_at == cursor_agent.created_at)
                        & (Agent.agent_uuid < cursor_agent.agent_uuid)
                    )
                )
        except ValueError:
            # Invalid cursor UUID, ignore it and return first page
            pass

    # Fetch limit + 1 to check if there are more pages
    query = query.limit(limit + 1)
    result = await db.execute(query)
    agents = result.scalars().all()

    # Check if there are more pages
    has_more = len(agents) > limit
    if has_more:
        agents = agents[:-1]  # Remove the extra item

    # Determine next cursor (UUID of last agent in this page)
    next_cursor: str | None = None
    if has_more and agents:
        next_cursor = str(agents[-1].agent_uuid)

    # Batch query: Get control counts for all agents at once
    # Join: Agent -> Policy -> policy_controls (junction table) -> Control
    # Count distinct enabled control IDs per agent
    # Performance: Filter NULL controls explicitly to avoid JSONB parsing on NULL rows
    # This allows the query planner to optimize better
    control_counts_map: dict[UUID, int] = {}
    if agents:
        control_counts_query = (
            select(
                Agent.agent_uuid,
                func.count(func.distinct(policy_controls.c.control_id)).label("count"),
            )
            .outerjoin(Policy, Agent.policy_id == Policy.id)
            .outerjoin(policy_controls, Policy.id == policy_controls.c.policy_id)
            .outerjoin(Control, policy_controls.c.control_id == Control.id)
            .where(
                Agent.agent_uuid.in_([agent.agent_uuid for agent in agents]),
                # Only count enabled controls: Control must exist AND be enabled
                # (enabled=true OR enabled key missing, default is True)
                Control.id.is_not(None),  # Exclude NULL controls (agents without policies)
                or_(
                    Control.data["enabled"].astext == "true",
                    ~Control.data.has_key("enabled"),
                ),
            )
            .group_by(Agent.agent_uuid)
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
        active_controls = control_counts_map.get(agent.agent_uuid, 0)

        summaries.append(
            AgentSummary(
                agent_id=str(agent.agent_uuid),
                agent_name=agent.name,
                policy_id=agent.policy_id,
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
    - If the agent name exists with the same UUID, updates registration data
    - If the agent name exists with a different UUID, returns 409 Conflict
    - If the UUID exists with a different name, returns 409 Conflict (no renames)

    conflict_mode controls registration conflict handling:
    - strict (default): preserve compatibility checks and conflict errors
    - overwrite: latest init payload replaces steps/evaluators and returns change summary

    Args:
        request: Agent metadata and step schemas
        db: Database session (injected)

    Returns:
        InitAgentResponse with created flag and active controls (if policy assigned)

    Raises:
        HTTPException 409: Agent name exists with different UUID
        HTTPException 500: Database error during creation/update
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

    # Look up by UUID first (primary key)
    result = await db.execute(select(Agent).where(Agent.agent_uuid == request.agent.agent_id))
    existing_by_uuid: Agent | None = result.scalars().first()

    # Perf optimization: If UUID exists, skip name query on hot path
    if existing_by_uuid is not None:
        # Validate name hasn't changed (no rename via initAgent)
        if existing_by_uuid.name != request.agent.agent_name:
            raise ConflictError(
                error_code=ErrorCode.AGENT_NAME_CONFLICT,
                detail=(
                    f"Agent ID '{request.agent.agent_id}' is already registered "
                    f"with name '{existing_by_uuid.name}'"
                ),
                resource="Agent",
                resource_id=str(request.agent.agent_id),
                hint="Use the existing agent name for this UUID or register a new UUID.",
                errors=[
                    ValidationErrorItem(
                        resource="Agent",
                        field="agent_name",
                        code="name_mismatch",
                        message=(
                            f"Agent ID '{request.agent.agent_id}' is already associated "
                            f"with name '{existing_by_uuid.name}'"
                        ),
                        value=request.agent.agent_name,
                    )
                ],
            )
        existing: Agent | None = existing_by_uuid
    else:
        # UUID doesn't exist, check if name is taken by different agent
        result = await db.execute(select(Agent).where(Agent.name == request.agent.agent_name))
        existing_by_name: Agent | None = result.scalars().first()
        existing = existing_by_name

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
            agent_uuid=request.agent.agent_id,
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
                f"Failed to create agent '{request.agent.agent_name}' ({request.agent.agent_id})",
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to create agent '{request.agent.agent_name}': database error",
                resource="Agent",
                operation="create",
            )
        return InitAgentResponse(created=created, controls=[])

    requested_uuid = request.agent.agent_id
    if existing.agent_uuid != requested_uuid:
        # UUID mismatch for the same name: return error
        raise ConflictError(
            error_code=ErrorCode.AGENT_UUID_CONFLICT,
            detail=f"Agent name '{request.agent.agent_name}' already exists with different UUID",
            resource="Agent",
            resource_id=request.agent.agent_name,
            hint="Use the existing agent's UUID or choose a different agent name.",
            errors=[
                ValidationErrorItem(
                    resource="Agent",
                    field="agent_id",
                    code="uuid_mismatch",
                    message=f"Agent '{request.agent.agent_name}' exists with a different UUID",
                    value=str(requested_uuid),
                )
            ],
        )

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
                f"Failed to update agent '{request.agent.agent_name}' ({request.agent.agent_id})",
                exc_info=True,
            )
            raise DatabaseError(
                detail=f"Failed to update agent '{request.agent.agent_name}': database error",
                resource="Agent",
                operation="update",
            )

    # If the existing agent has a policy, include its controls; otherwise empty list
    controls = []
    if existing.policy_id is not None:
        controls = await list_controls_for_agent(existing.agent_uuid, db)

    return InitAgentResponse(
        created=created,
        controls=controls,
        overwrite_applied=overwrite_applied,
        overwrite_changes=overwrite_changes,
    )


@router.get(
    "/{agent_id}",
    response_model=GetAgentResponse,
    summary="Get agent details",
    response_description="Agent metadata and registered steps",
)
async def get_agent(agent_id: UUID, db: AsyncSession = Depends(get_async_db)) -> GetAgentResponse:
    """
    Retrieve agent metadata and all registered steps.

    Returns the latest version of each step (deduplicated by type+name).

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        GetAgentResponse with agent metadata and step list

    Raises:
        HTTPException 404: Agent not found
        HTTPException 422: Agent data is corrupted
    """
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    existing: Agent | None = result.scalars().first()
    if existing is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered via initAgent.",
        )

    try:
        data_model = AgentData.model_validate(existing.data)
    except ValidationError:
        _logger.error(
            f"Failed to parse agent data for agent '{existing.name}' ({agent_id})",
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
            f"Failed to parse agent metadata for agent '{existing.name}' ({agent_id})",
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


@router.post(
    "/{agent_id}/policy/{policy_id}",
    response_model=SetPolicyResponse,
    summary="Assign policy to agent",
    response_description="Success status with previous policy ID",
)
async def set_agent_policy(
    agent_id: UUID, policy_id: int, db: AsyncSession = Depends(get_async_db)
) -> SetPolicyResponse:
    """
    Assign a policy to an agent, replacing any existing policy assignment.

    The agent will immediately inherit all controls from the assigned policy.

    Args:
        agent_id: UUID of the agent
        policy_id: ID of the policy to assign
        db: Database session (injected)

    Returns:
        SetPolicyResponse with success flag and previous policy ID (if any)

    Raises:
        HTTPException 404: Agent or policy not found
        HTTPException 500: Database error during assignment
    """
    # Find agent
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered.",
        )

    # Find policy by id
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

    # Validate controls can run on this agent
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

    # Store old policy ID if exists
    old_policy_id: int | None = None
    if agent.policy_id is not None:
        old_policy_id = agent.policy_id

    # Assign new policy
    agent.policy_id = policy.id
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to assign policy '{policy_id}' to agent '{agent.name}' ({agent_id})",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to assign policy to agent '{agent.name}': database error",
            resource="Agent",
            operation="assign policy",
        )

    return SetPolicyResponse(success=True, old_policy_id=old_policy_id)


@router.get(
    "/{agent_id}/policy",
    response_model=GetPolicyResponse,
    summary="Get agent's assigned policy",
    response_description="Policy ID",
)
async def get_agent_policy(
    agent_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> GetPolicyResponse:
    """
    Retrieve the policy currently assigned to an agent.

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        GetPolicyResponse with policy ID

    Raises:
        HTTPException 404: Agent not found or agent has no policy assigned
    """
    # Find agent
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered.",
        )

    # Check if agent has a policy
    if agent.policy_id is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Agent '{agent.name}' has no policy assigned",
            resource="Policy",
            hint="Assign a policy to the agent using POST /{agent_id}/policy/{policy_id}.",
        )

    # Find policy
    policy_result = await db.execute(select(Policy).where(Policy.id == agent.policy_id))
    policy: Policy | None = policy_result.scalars().first()
    if policy is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=(
                f"Policy with ID '{agent.policy_id}' not found "
                f"(referenced by agent '{agent.name}')"
            ),
            resource="Policy",
            resource_id=str(agent.policy_id),
            hint="The referenced policy may have been deleted. Assign a new policy to the agent.",
        )

    return GetPolicyResponse(policy_id=policy.id)


@router.delete(
    "/{agent_id}/policy",
    response_model=DeletePolicyResponse,
    summary="Remove agent's policy assignment",
    response_description="Success confirmation",
)
async def delete_agent_policy(
    agent_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> DeletePolicyResponse:
    """
    Remove the policy assignment from an agent.

    The agent will no longer have any protection controls active.

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        DeletePolicyResponse with success flag

    Raises:
        HTTPException 404: Agent not found or agent has no policy assigned
        HTTPException 500: Database error during removal
    """
    # Find agent
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered.",
        )

    # Check if agent has a policy
    if agent.policy_id is None:
        raise NotFoundError(
            error_code=ErrorCode.POLICY_NOT_FOUND,
            detail=f"Agent '{agent.name}' has no policy assigned",
            resource="Policy",
            hint="The agent does not have a policy to remove.",
        )

    # Remove policy assignment
    agent.policy_id = None
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        _logger.error(
            f"Failed to remove policy from agent '{agent.name}' ({agent_id})",
            exc_info=True,
        )
        raise DatabaseError(
            detail=f"Failed to remove policy from agent '{agent.name}': database error",
            resource="Agent",
            operation="remove policy",
        )

    return DeletePolicyResponse(success=True)


@router.get(
    "/{agent_id}/controls",
    response_model=AgentControlsResponse,
    summary="List agent's active controls",
    response_description="List of controls from agent's policy",
)
async def list_agent_controls(
    agent_id: UUID, db: AsyncSession = Depends(get_async_db)
) -> AgentControlsResponse:
    """
    List all protection controls active for an agent.

    Controls are inherited from the agent's assigned policy.
    Returns an empty list if the agent has no policy.

    Args:
        agent_id: UUID of the agent
        db: Database session (injected)

    Returns:
        AgentControlsResponse with list of controls (empty if no policy)

    Raises:
        HTTPException 404: Agent not found
    """
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered.",
        )

    if agent.policy_id is None:
        return AgentControlsResponse(controls=[])

    controls = await list_controls_for_agent(agent_id, db)
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
    "/{agent_id}/evaluators",
    response_model=ListEvaluatorsResponse,
    summary="List agent's registered evaluator schemas",
    response_description="Evaluator schemas registered with this agent",
)
async def list_agent_evaluators(
    agent_id: UUID,
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
        agent_id: UUID of the agent
        cursor: Optional cursor for pagination (name of last evaluator from previous page)
        limit: Pagination limit (default 20, max 100)
        db: Database session (injected)

    Returns:
        ListEvaluatorsResponse with evaluator schemas and pagination

    Raises:
        HTTPException 404: Agent not found
    """
    # Clamp limit
    limit = min(max(1, limit), _MAX_PAGINATION_LIMIT)

    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered.",
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
    "/{agent_id}/evaluators/{evaluator_name}",
    response_model=EvaluatorSchemaItem,
    summary="Get specific evaluator schema",
    response_description="Evaluator schema details",
)
async def get_agent_evaluator(
    agent_id: UUID,
    evaluator_name: str,
    db: AsyncSession = Depends(get_async_db),
) -> EvaluatorSchemaItem:
    """
    Get a specific evaluator schema registered with an agent.

    Args:
        agent_id: UUID of the agent
        evaluator_name: Name of the evaluator
        db: Database session (injected)

    Returns:
        EvaluatorSchemaItem with schema details

    Raises:
        HTTPException 404: Agent or evaluator not found
    """
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered.",
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
    "/{agent_id}",
    response_model=PatchAgentResponse,
    summary="Modify agent (remove steps/evaluators)",
    response_description="Lists of removed items",
)
async def patch_agent(
    agent_id: UUID,
    request: PatchAgentRequest,
    db: AsyncSession = Depends(get_async_db),
) -> PatchAgentResponse:
    """
    Remove steps and/or evaluators from an agent.

    This is the complement to initAgent which only adds items.
    Removals are idempotent - attempting to remove non-existent items is not an error.

    Args:
        agent_id: UUID of the agent
        request: Lists of step/evaluator identifiers to remove
        db: Database session (injected)

    Returns:
        PatchAgentResponse with lists of actually removed items

    Raises:
        HTTPException 404: Agent not found
        HTTPException 500: Database error during update
    """
    result = await db.execute(select(Agent).where(Agent.agent_uuid == agent_id))
    agent: Agent | None = result.scalars().first()
    if agent is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail=f"Agent with ID '{agent_id}' not found",
            resource="Agent",
            resource_id=str(agent_id),
            hint="Verify the agent ID is correct and the agent has been registered.",
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

        # Check if any controls reference evaluators being removed
        if agent.policy_id is not None:
            # Get all controls for this agent's policy
            controls = await list_controls_for_agent(agent.agent_uuid, db)
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
                f"Failed to patch agent '{agent.name}' ({agent_id})",
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
