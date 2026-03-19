#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_PATH="${OPEN_SHELL_POLICY_PATH:-$SCRIPT_DIR/openshell_policy_companion.yaml}"

cd "$SCRIPT_DIR"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY must be set before launching the demo." >&2
  exit 1
fi

if ! command -v openshell >/dev/null 2>&1; then
  echo "The openshell CLI is not available in this environment." >&2
  echo "Run 'uv sync' in this example directory first." >&2
  exit 1
fi

exec openshell sandbox create \
  --policy "$POLICY_PATH" \
  -- env \
    OPENAI_API_KEY="$OPENAI_API_KEY" \
    AGENT_CONTROL_URL="${AGENT_CONTROL_URL:-http://localhost:8000}" \
    DEMO_MODEL="${DEMO_MODEL:-openai:gpt-4o-mini}" \
    OPEN_SHELL_REAL_SANDBOX=true \
    DEMO_SIMULATE_OPENSHELL=false \
    uv run python autonomous_incident_responder.py
