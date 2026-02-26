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

# Copy alembic configuration from server directory
COPY server/alembic.ini ./

# Copy shared dependencies (Workspaces)
COPY models/ models/
COPY engine/ engine/
COPY evaluators/ evaluators/

# Copy server application
COPY server/ server/

# Install server + bundled runtime packages (engine/evaluators/models)
# We ignore the lockfile if it's missing or out of sync to ensure build succeeds during dev
RUN uv sync \
    --package agent-control-server \
    --package agent-control-engine \
    --package agent-control-evaluators \
    --package agent-control-models \
    --no-dev \
  || uv sync \
    --package agent-control-server \
    --package agent-control-engine \
    --package agent-control-evaluators \
    --package agent-control-models \
    --no-dev \
    --frozen

# Add the virtual environment to PATH
ENV PATH="/app/.venv/bin:$PATH"

# Set default environment variables
ENV HOST=0.0.0.0
ENV PORT=8000

# Expose the port
EXPOSE 8000

# Copy and configure entrypoint script
COPY server/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Set entrypoint to run migrations before starting server
ENTRYPOINT ["docker-entrypoint.sh"]

# Run the server entrypoint defined in pyproject.toml
CMD ["agent-control-server"]
