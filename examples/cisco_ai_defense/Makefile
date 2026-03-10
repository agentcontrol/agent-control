.PHONY: help run seed decorator-run decorator-post-run decorator-all-run register

help:
	@echo "Cisco AI Defense examples"
	@echo "  make run                 - run direct Chat Inspection demo"
	@echo "  make seed                - seed controls/policy on server"
	@echo "  make register            - register agent and persist .agent_id"
	@echo "  make decorator-post-run  - run decorator POST-only (PII) example"
	@echo "  make decorator-all-run   - run combined pre + post cases"

run:
	uv sync && uv run chat_inspect_demo.py

seed:
	uv sync && uv run seed_policy.py

decorator-post-run:
	@if [ -z "$$AGENT_ID" ]; then echo "AGENT_ID is required"; exit 2; fi
	uv sync && uv run chat_guarded_post.py --agent-id $$AGENT_ID --agent-name ai-defense-demo

decorator-all-run:
	@if [ -z "$$AGENT_ID" ]; then echo "AGENT_ID is required"; exit 2; fi
	uv sync && uv run chat_guarded_all.py --agent-id $$AGENT_ID --agent-name ai-defense-demo

register:
	uv sync && uv run register_agent.py --agent-name ai-defense-demo
