"""Inference gateway policy endpoints for the serial POC."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from agent_control_engine.core import ControlEngine
from agent_control_evaluator_budget.budget import (  # type: ignore[import-untyped]
    BudgetEvaluator,
    BudgetEvaluatorConfig,
)
from agent_control_models import (
    ActionDecision,
    EvaluationRequest,
    EvaluationResponse,
    GatewayBudgetState,
    GatewayModelCandidate,
    GatewayPreflightRequest,
    GatewayPreflightResponse,
    GatewayRouteDecisionResponse,
    GatewayUsageSettlementRequest,
    GatewayUsageSettlementResponse,
    JSONObject,
    Step,
)
from agent_control_models.errors import ErrorCode
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from ..auth_framework import Operation, Principal, require_operation
from ..db import AsyncSessionLocal
from ..errors import ForbiddenError, NotFoundError
from ..models import Agent
from ..services.controls import ControlService
from .evaluation import ControlAdapter

router = APIRouter(prefix="/gateway/agents", tags=["inference-gateway"])


async def _agent_context(request: Request) -> dict[str, str]:
    """Bind runtime authorization to the route agent or supplied stream UUID."""
    target_id = request.path_params["agent_name"]
    target_type = "agent"
    try:
        body = await request.json()
    except (TypeError, ValueError):
        body = None
    if isinstance(body, dict) and body.get("log_stream_id") is not None:
        raw_stream_id = body["log_stream_id"]
        target_type = "log_stream"
        try:
            target_id = str(UUID(raw_stream_id))
        except (ValueError, TypeError, AttributeError):
            target_id = str(raw_stream_id)
    return {"target_type": target_type, "target_id": target_id}


_runtime_agent = require_operation(Operation.RUNTIME_USE, context_builder=_agent_context)


async def _get_gateway_controls(agent_name: str, principal: Principal) -> list[ControlAdapter]:
    """Load agent controls plus bindings for the authenticated runtime target."""
    if principal.target_type == "agent" and principal.target_id == agent_name:
        target_type = "agent"
        target_id = agent_name
    elif principal.target_type == "log_stream" and principal.target_id is not None:
        try:
            target_id = str(UUID(principal.target_id))
        except ValueError:
            target_id = ""
        if not target_id:
            raise ForbiddenError(
                error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
                detail="Gateway runtime identity must be bound to a valid log stream UUID.",
            )
        target_type = "log_stream"
    else:
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail=(
                "Gateway requests must use a runtime identity bound to this agent or log stream."
            ),
        )
    async with AsyncSessionLocal() as db:
        agent_result = await db.execute(
            select(Agent).where(
                Agent.name == agent_name,
                Agent.namespace_key == principal.namespace_key,
            )
        )
        if agent_result.scalar_one_or_none() is None:
            raise NotFoundError(
                error_code=ErrorCode.AGENT_NOT_FOUND,
                detail=f"Agent '{agent_name}' not found",
                resource="Agent",
                resource_id=agent_name,
            )
        runtime_controls = await ControlService(db).list_runtime_controls_for_agent(
            agent_name,
            namespace_key=principal.namespace_key,
            target_type=target_type,
            target_id=target_id,
            allow_invalid_step_name_regex=True,
        )
    return [
        ControlAdapter(control.id, control.name, control.control)
        for control in runtime_controls
    ]


def _gateway_budget_control(
    controls: list[ControlAdapter],
) -> tuple[ControlAdapter, BudgetEvaluatorConfig] | None:
    """Find an existing bound budget control configured for gateway routing."""
    for control in controls:
        for _, evaluator_spec in control.control.iter_condition_leaf_parts():
            if evaluator_spec.name != "budget" or "gateway_routing" not in evaluator_spec.config:
                continue
            config = BudgetEvaluatorConfig.model_validate(evaluator_spec.config)
            return control, config
    return None


def _budget_state_from_metadata(metadata: object) -> GatewayBudgetState | None:
    if not isinstance(metadata, dict):
        return None
    route = metadata.get("gateway_route", metadata)
    if not isinstance(route, dict):
        return None
    budget = route.get("budget")
    if not isinstance(budget, dict):
        return None
    return GatewayBudgetState.model_validate(budget)


async def _evaluate_controls(
    agent_name: str,
    request: GatewayPreflightRequest,
    principal: Principal,
) -> EvaluationResponse:
    """Evaluate current agent controls, including enabled agent target bindings."""
    controls = await _get_gateway_controls(agent_name, principal)
    input_data: JSONObject = {
        "task_type": request.task_type,
        "task_context": request.task_context,
        "prompt": request.prompt,
        "candidate_models": [
            {
                "provider": candidate.provider,
                "model": candidate.model,
                "protocol": candidate.protocol,
            }
            for candidate in request.candidate_models
        ],
    }
    if request.model is not None:
        input_data["model"] = request.model
    evaluation = EvaluationRequest(
        agent_name=agent_name,
        stage="pre",
        step=Step(
            type="llm",
            name="inference-gateway-preflight",
            input=input_data,
            output=None,
            context=None,
            tools=None,
            ground_truth=None,
            children=None,
        ),
    )
    return await ControlEngine(controls).process(evaluation)


def _find_gateway_route(
    evaluation: EvaluationResponse,
) -> tuple[str, dict[str, object], ActionDecision] | None:
    """Extract gateway routing metadata from the normal control match flow."""
    for match in evaluation.matches or []:
        if match.action != "route":
            continue
        route = (match.result.metadata or {}).get("gateway_route")
        if isinstance(route, dict):
            return match.control_name, route, match.action
    return None


async def _decide(
    agent_name: str,
    request: GatewayPreflightRequest,
    principal: Principal,
) -> tuple[GatewayPreflightResponse, GatewayModelCandidate | None, ActionDecision | None]:
    if request.agent_name is not None and request.agent_name != agent_name:
        raise ForbiddenError(
            error_code=ErrorCode.AUTH_INSUFFICIENT_PRIVILEGES,
            detail="Request agent_name must match the authenticated agent target.",
        )
    evaluation = await _evaluate_controls(agent_name, request, principal)
    route_result = _find_gateway_route(evaluation)
    policy_name, route, action = route_result if route_result is not None else (None, {}, None)
    budget = _budget_state_from_metadata(route)
    candidate: GatewayModelCandidate | None = None
    provider = route.get("provider")
    model = route.get("model")
    protocol = route.get("protocol")
    route_protocol: Literal["openai", "anthropic"] | None
    if protocol == "openai":
        route_protocol = "openai"
    elif protocol == "anthropic":
        route_protocol = "anthropic"
    else:
        route_protocol = None
    if isinstance(provider, str) and isinstance(model, str) and route_protocol is not None:
        candidate = GatewayModelCandidate(
            provider=provider, model=model, protocol=route_protocol
        )
    allowed = bool(route.get("allowed", False)) and evaluation.is_safe and candidate is not None
    if agent_name == "claude-code" and candidate is not None:
        allowed = (
            allowed
            and candidate.provider == "anthropic"
            and candidate.protocol == "anthropic"
        )
        if not allowed:
            candidate = None
    denied_match = next(
        (match for match in evaluation.matches or [] if match.action == "deny"), None
    )
    if denied_match is not None:
        policy_name = denied_match.control_name
        action = denied_match.action
    reason_value = route.get("reason")
    reason = (
        reason_value
        if isinstance(reason_value, str)
        else "No gateway routing evaluator is configured on a bound control."
    )
    if denied_match is not None or not evaluation.is_safe:
        reason = (
            f"Control '{denied_match.control_name}' denied the inference request."
            if denied_match is not None
            else evaluation.reason or "An Agent Control control denied this inference request."
        )
    elif not allowed and agent_name == "claude-code":
        reason = "Claude Code routes must use an Anthropic-compatible provider and protocol."
    if not allowed:
        return (
            GatewayPreflightResponse(
                allowed=False,
                policy=policy_name or "agent-controls",
                budget=budget,
                reason=reason,
            ),
            None,
            action,
        )
    return (
        GatewayPreflightResponse(
            allowed=True,
            policy=policy_name or "agent-controls",
            budget=budget,
            reason=reason,
        ),
        candidate,
        action,
    )


@router.post("/{agent_name}/preflight", response_model=GatewayPreflightResponse)
async def preflight(
    request: GatewayPreflightRequest,
    agent_name: str,
    principal: Principal = Depends(_runtime_agent),
) -> GatewayPreflightResponse:
    """Evaluate controls and policy eligibility before inference."""
    response, _, _ = await _decide(agent_name, request, principal)
    return response


@router.post("/{agent_name}/route-decision", response_model=GatewayRouteDecisionResponse)
async def route_decision(
    request: GatewayPreflightRequest,
    agent_name: str,
    principal: Principal = Depends(_runtime_agent),
) -> GatewayRouteDecisionResponse:
    """Select an allowed model for the authenticated agent and classified task."""
    response, candidate, action = await _decide(agent_name, request, principal)
    return GatewayRouteDecisionResponse(
        **response.model_dump(),
        provider=candidate.provider if candidate is not None else None,
        model=candidate.model if candidate is not None else None,
        protocol=candidate.protocol if candidate is not None else None,
        task_type=request.task_type,
        decision="route" if candidate is not None and response.allowed else "deny",
        action=action,
    )


@router.post("/{agent_name}/usage-settlement", response_model=GatewayUsageSettlementResponse)
async def usage_settlement(
    request: GatewayUsageSettlementRequest,
    agent_name: str,
    principal: Principal = Depends(_runtime_agent),
) -> GatewayUsageSettlementResponse:
    """Accumulate completed inference usage against the authenticated agent budget."""
    controls = await _get_gateway_controls(agent_name, principal)
    budget_control = _gateway_budget_control(controls)
    if budget_control is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail="No bound budget evaluator with gateway routing is configured for this agent.",
            resource="GatewayRoutingControl",
            resource_id=agent_name,
        )
    control, config = budget_control
    result = await BudgetEvaluator(config).evaluate(
        {
            "input_tokens": request.input_tokens,
            "output_tokens": request.output_tokens,
            "model": request.model,
        }
    )
    metadata = result.metadata or {}
    budget = _budget_state_from_metadata(metadata)
    if budget is None:
        raise NotFoundError(
            error_code=ErrorCode.AGENT_NOT_FOUND,
            detail="The bound budget evaluator did not return gateway budget state.",
            resource="GatewayRoutingControl",
            resource_id=control.name,
        )
    over_limit = budget.over_limit
    reason = (
        "Usage settled; the authenticated agent budget is exhausted."
        if over_limit
        else "Usage settled against the authenticated agent budget."
    )
    return GatewayUsageSettlementResponse(policy=control.name, budget=budget, reason=reason)
