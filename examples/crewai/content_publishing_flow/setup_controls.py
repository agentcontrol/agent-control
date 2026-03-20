"""
Setup script for Content Publishing Flow controls.

Creates Agent Control controls for each stage of the CrewAI Flow pipeline:
- Intake: JSON evaluator to validate required fields
- Research: LIST evaluator to block banned sources
- Fact-Check: REGEX evaluator to flag unverified claims
- Draft: REGEX evaluator for PII, LIST evaluator for banned topics
- Compliance: JSON evaluator for legal review fields
- Editor: REGEX for PII cleanup (executive summary check is client-side)
- Human Review: STEER action for manager approval on internal memos

Run once before running publishing_flow.py:
    uv run --active python setup_controls.py
"""

import asyncio
import os

from agent_control import Agent, AgentControlClient, agents, controls

AGENT_NAME = "content-publishing-flow"
SERVER_URL = os.getenv("AGENT_CONTROL_URL", "http://localhost:8000")


async def create_control_safe(
    client: AgentControlClient,
    name: str,
    data: dict,
) -> int:
    """Create a control, handling 409 conflicts gracefully. Returns control_id."""
    try:
        result = await controls.create_control(client, name=name, data=data)
        control_id = result["control_id"]
        print(f"  + Created control: {name} (ID: {control_id})")
        return control_id
    except Exception as e:
        if "409" in str(e):
            print(f"  ~ Control '{name}' already exists, looking it up...")
            controls_list = await controls.list_controls(client, name=name, limit=1)
            if controls_list["controls"]:
                control_id = controls_list["controls"][0]["id"]
                print(f"  ~ Using existing control (ID: {control_id})")
                return control_id
            else:
                print(f"  ! Could not find existing control '{name}'")
                raise SystemExit(1)
        else:
            print(f"  ! Error creating control '{name}': {e}")
            raise


async def add_control_to_agent_safe(
    client: AgentControlClient,
    agent_name: str,
    control_id: int,
    control_name: str,
) -> None:
    """Associate a control with an agent, handling duplicates gracefully."""
    try:
        await agents.add_agent_control(client, agent_name, control_id)
        print(f"  + Associated '{control_name}' with agent")
    except Exception as e:
        if "409" in str(e) or "already" in str(e).lower():
            print(f"  ~ '{control_name}' already associated with agent (OK)")
        else:
            print(f"  ! Failed to associate '{control_name}': {e}")
            raise


async def setup_publishing_controls():
    """Create all controls for the content publishing flow pipeline."""
    async with AgentControlClient(base_url=SERVER_URL) as client:

        # =====================================================================
        # 1. Register the Agent
        # =====================================================================
        print("Registering agent...")
        agent = Agent(
            agent_name=AGENT_NAME,
            agent_description=(
                "Content publishing flow with routing, embedded crews, "
                "and Agent Control guardrails at each pipeline stage"
            ),
        )

        try:
            await agents.register_agent(client, agent, steps=[])
            print(f"  + Agent registered: {AGENT_NAME}")
        except Exception as e:
            print(f"  ~ Agent may already exist: {e}")

        # =====================================================================
        # 2. Create Controls
        # =====================================================================
        print("\nCreating controls...")
        control_ids: list[tuple[int, str]] = []

        # ------------------------------------------------------------------
        # INTAKE STAGE: JSON evaluator - require topic, audience, content_type
        # ------------------------------------------------------------------
        intake_validation = {
            "description": "Validate content request has required fields (topic, audience, content_type)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["validate_request"],
                "stages": ["pre"],
            },
            "selector": {
                "path": "input.request",
            },
            "evaluator": {
                "name": "json",
                "config": {
                    "required_fields": ["topic", "audience", "content_type"],
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-intake-validation", intake_validation)
        control_ids.append((cid, "flow-intake-validation"))

        # ------------------------------------------------------------------
        # RESEARCH STAGE: LIST evaluator - block banned sources
        # ------------------------------------------------------------------
        banned_sources = {
            "description": "Block research that references banned or unreliable sources",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["research_topic"],
                "stages": ["post"],
            },
            "selector": {
                "path": "output",
            },
            "evaluator": {
                "name": "list",
                "config": {
                    "values": [
                        "infowars.com",
                        "naturalcures.com",
                        "conspiracydaily.net",
                        "fakenews.org",
                        "unverifiedsource.com",
                    ],
                    "logic": "any",
                    "match_mode": "contains",
                    "case_sensitive": False,
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-research-banned-sources", banned_sources)
        control_ids.append((cid, "flow-research-banned-sources"))

        # ------------------------------------------------------------------
        # FACT-CHECK STAGE: REGEX evaluator - flag unverified claims/URLs
        # ------------------------------------------------------------------
        unverified_claims = {
            "description": "Flag fact-check results that contain unverified claim markers",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["fact_check"],
                "stages": ["post"],
            },
            "selector": {
                "path": "output",
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": (
                        r"(?i)"
                        r"(?:UNVERIFIED|UNCONFIRMED|DEBUNKED|RETRACTED|FABRICATED)"
                        r"|(?:no\s+credible\s+source)"
                        r"|(?:cannot\s+be\s+verified)"
                    ),
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-factcheck-unverified", unverified_claims)
        control_ids.append((cid, "flow-factcheck-unverified"))

        # ------------------------------------------------------------------
        # DRAFT STAGE: REGEX evaluator - block PII in draft content
        # ------------------------------------------------------------------
        draft_pii = {
            "description": "Block drafts containing PII (SSN, email, phone)",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["write_draft"],
                "stages": ["post"],
            },
            "selector": {
                "path": "output",
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": (
                        r"(?:"
                        r"\b\d{3}-\d{2}-\d{4}\b"               # SSN
                        r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"  # Email
                        r"|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"      # Phone
                        r")"
                    ),
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-draft-pii-block", draft_pii)
        control_ids.append((cid, "flow-draft-pii-block"))

        # ------------------------------------------------------------------
        # DRAFT STAGE: LIST evaluator - block banned topics
        # ------------------------------------------------------------------
        banned_topics = {
            "description": "Block drafts that contain banned or restricted topics",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["write_draft"],
                "stages": ["post"],
            },
            "selector": {
                "path": "output",
            },
            "evaluator": {
                "name": "list",
                "config": {
                    "values": [
                        "insider trading",
                        "market manipulation",
                        "ponzi scheme",
                        "money laundering",
                        "classified information",
                    ],
                    "logic": "any",
                    "match_mode": "contains",
                    "case_sensitive": False,
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-draft-banned-topics", banned_topics)
        control_ids.append((cid, "flow-draft-banned-topics"))

        # ------------------------------------------------------------------
        # COMPLIANCE STAGE: JSON evaluator - require disclaimer + legal_reviewed
        # ------------------------------------------------------------------
        legal_review = {
            "description": "Require disclaimer and legal_reviewed=true in compliance output",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["legal_review"],
                "stages": ["post"],
            },
            "selector": {
                "path": "output",
            },
            "evaluator": {
                "name": "json",
                "config": {
                    "required_fields": ["disclaimer", "legal_reviewed"],
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-compliance-legal-review", legal_review)
        control_ids.append((cid, "flow-compliance-legal-review"))

        # ------------------------------------------------------------------
        # EDITOR STAGE: REGEX evaluator - clean PII from edited content
        # ------------------------------------------------------------------
        editor_pii = {
            "description": "Block edited content that still contains PII",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["edit_content"],
                "stages": ["post"],
            },
            "selector": {
                "path": "output",
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": (
                        r"(?:"
                        r"\b\d{3}-\d{2}-\d{4}\b"
                        r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
                        r"|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"
                        r")"
                    ),
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-editor-pii-block", editor_pii)
        control_ids.append((cid, "flow-editor-pii-block"))

        # NOTE: Executive summary check for press releases is handled
        # client-side in the flow code (compliance_review stage), because
        # detecting the ABSENCE of text requires negative lookahead which
        # the regex evaluator does not support.

        # ------------------------------------------------------------------
        # HUMAN REVIEW STAGE: STEER - pause for manager approval
        # ------------------------------------------------------------------
        human_review_steer = {
            "description": "Steer flow to pause for manager approval on internal memos",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["request_human_review"],
                "stages": ["pre"],
            },
            "selector": {
                "path": "input.content_type",
            },
            "evaluator": {
                "name": "list",
                "config": {
                    "values": ["internal_memo"],
                    "logic": "any",
                    "match_mode": "exact",
                    "case_sensitive": False,
                },
            },
            "action": {
                "decision": "steer",
                "steering_context": {
                    "message": '{"required_actions": ["get_manager_approval"], "reason": "Internal memos require manager approval before distribution.", "retry_with": {"approved": true}}',
                },
            },
        }
        cid = await create_control_safe(client, "flow-human-review-steer", human_review_steer)
        control_ids.append((cid, "flow-human-review-steer"))

        # ------------------------------------------------------------------
        # AUTO-PUBLISH STAGE: REGEX - final PII scan before publishing
        # ------------------------------------------------------------------
        publish_pii = {
            "description": "Final PII scan before auto-publishing content",
            "enabled": True,
            "execution": "server",
            "scope": {
                "step_types": ["tool"],
                "step_names": ["publish_content"],
                "stages": ["pre"],
            },
            "selector": {
                "path": "input.content",
            },
            "evaluator": {
                "name": "regex",
                "config": {
                    "pattern": (
                        r"(?:"
                        r"\b\d{3}-\d{2}-\d{4}\b"
                        r"|[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
                        r"|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"
                        r")"
                    ),
                },
            },
            "action": {"decision": "deny"},
        }
        cid = await create_control_safe(client, "flow-publish-pii-scan", publish_pii)
        control_ids.append((cid, "flow-publish-pii-scan"))

        # =====================================================================
        # 3. Associate All Controls with Agent
        # =====================================================================
        print("\nAssociating controls with agent...")
        for control_id, control_name in control_ids:
            await add_control_to_agent_safe(client, AGENT_NAME, control_id, control_name)

        # =====================================================================
        # Summary
        # =====================================================================
        print("\n" + "=" * 60)
        print("Setup complete!")
        print("=" * 60)
        print(f"\nAgent: {AGENT_NAME}")
        print(f"Server: {SERVER_URL}")
        print(f"Controls created: {len(control_ids)}")
        print("\nControls by pipeline stage:")
        print("  INTAKE:")
        print("    - flow-intake-validation (JSON: require topic, audience, content_type)")
        print("  RESEARCH:")
        print("    - flow-research-banned-sources (LIST: block unreliable sources)")
        print("    - flow-factcheck-unverified (REGEX: flag unverified claims)")
        print("  DRAFT:")
        print("    - flow-draft-pii-block (REGEX: block PII)")
        print("    - flow-draft-banned-topics (LIST: block restricted topics)")
        print("  COMPLIANCE (high_risk path):")
        print("    - flow-compliance-legal-review (JSON: require disclaimer + legal_reviewed)")
        print("    - flow-editor-pii-block (REGEX: block PII in edits)")
        print("    - Executive summary check (client-side in flow code)")
        print("  HUMAN REVIEW (escalation path):")
        print("    - flow-human-review-steer (STEER: manager approval)")
        print("  AUTO-PUBLISH (low_risk path):")
        print("    - flow-publish-pii-scan (REGEX: final PII scan)")
        print("\nRun the flow:  uv run --active python -m content_publishing_flow.main")


if __name__ == "__main__":
    print("=" * 60)
    print("Content Publishing Flow - Control Setup")
    print("=" * 60)
    print()
    asyncio.run(setup_publishing_controls())
