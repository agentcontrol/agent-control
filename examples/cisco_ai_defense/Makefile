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
	uv sync && uv run setup_ai_defense_controls.py

decorator-post-run:
	uv sync && uv run chat_guarded_post.py --agent-name ai-defense-demo

decorator-all-run:
	uv sync && uv run chat_guarded_all.py --agent-name ai-defense-demo

register:
	uv sync && uv run register_agent.py --agent-name ai-defense-demo
