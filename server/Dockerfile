# Dockerfile for Agent Control Server
#
# Build from the repository root:
#   docker build -t agent-control-server -f server/Dockerfile .
#
# Run:
#   docker run -p 8000:8000 agent-control-server

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Configure uv environment variables
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy workspace definition
COPY pyproject.toml uv.lock* ./

# Copy shared dependencies (Workspaces)
COPY models/ models/
COPY engine/ engine/

# Copy server application
COPY server/ server/

# Install the server package and its dependencies
# We ignore the lockfile if it's missing or out of sync to ensure build succeeds during dev
RUN uv sync --package agent-control-server --no-dev || uv sync --package agent-control-server --no-dev --frozen

# Add the virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Set default environment variables
ENV HOST=0.0.0.0
ENV PORT=8000

# Expose the port
EXPOSE 8000

# Run the server entrypoint defined in pyproject.toml
CMD ["agent-control-server"]
