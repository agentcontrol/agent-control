#!/bin/bash
set -e  # Exit on error

# Support non-interactive mode for curl | sh
NON_INTERACTIVE=${NON_INTERACTIVE:-false}
if [ -t 0 ]; then
    # Running interactively (not piped)
    NON_INTERACTIVE=false
else
    # Running non-interactively (piped from curl)
    NON_INTERACTIVE=true
fi

echo "=========================================="
echo "Agent Control - Quick Setup"
echo "=========================================="
echo ""

if [ "$NON_INTERACTIVE" = true ]; then
    echo "Running in non-interactive mode..."
    echo ""
fi

# 1. Check Python version
echo "1. Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "   Found Python $PYTHON_VERSION"

# Extract major and minor version (e.g., 3.12, 3.14)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

# Check if Python >= 3.12
if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 12 ]]; then
    echo "   ⚠ Error: Python 3.12+ is required, but found $PYTHON_VERSION"
    echo "   Please install Python 3.12 or higher"
    exit 1
else
    echo "   ✓ Python $PYTHON_VERSION detected (3.12+ required)"
fi
echo ""

# 2. Create virtual environment
echo "2. Creating virtual environment..."
if [ -d ".venv" ]; then
    echo "   Virtual environment already exists"
else
    python3 -m venv .venv
    echo "   ✓ Virtual environment created"
fi

echo "   Activating virtual environment..."
source .venv/bin/activate
echo "   ✓ Virtual environment activated"
echo ""

# 3. Cleanup and pull Docker images
echo "3. Setting up Docker containers..."
echo "   Cleaning up old containers..."
docker rm -f agent_control_postgres agent-control-server 2>/dev/null || true
echo "   ✓ Cleanup complete"
echo ""

echo "   Pulling latest Docker image..."
docker pull galileoai/agent-control-server:latest
echo "   ✓ Image pulled"
echo ""

# 4. Run Docker containers
echo "4. Starting PostgreSQL and Agent Control Server..."
docker run -d \
  --name agent_control_postgres \
  -p 5432:5432 \
  -e POSTGRES_DB=agent_control \
  -e POSTGRES_USER=agent_control \
  -e POSTGRES_PASSWORD=agent_control \
  postgres:16-alpine

echo "   Waiting for PostgreSQL to be ready..."
sleep 10

docker run -d \
  --name agent-control-server \
  -p 8000:8000 \
  --link agent_control_postgres:postgres \
  -e DATABASE_URL=postgresql+psycopg://agent_control:agent_control@agent_control_postgres:5432/agent_control \
  -e HOST=0.0.0.0 \
  -e PORT=8000 \
  galileoai/agent-control-server:latest

echo "   ✓ Containers started"
echo ""

# Wait for server to be ready
echo "   Waiting for server to initialize..."
sleep 5
echo ""

# Show running containers
echo "5. Checking container status..."
docker ps --filter "name=agent_control" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

# 6. Show server logs
echo "6. Checking server logs..."
echo "   (Waiting for startup to complete...)"
sleep 3
docker logs agent-control-server 2>&1 | tail -15
echo ""

# 7. Install SDK
echo "7. Installing Agent Control SDK..."
pip install --upgrade agent-control-sdk
echo "   ✓ SDK installed"
echo ""

echo "=========================================="
echo "✓ Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  • Server is running at http://localhost:8000"
echo "  • Check server health: curl http://localhost:8000/health"
echo "  • View server logs: docker logs -f agent-control-server"
echo "  • Stop servers: docker rm -f agent_control_postgres agent-control-server"
echo ""
echo "Virtual environment is activated. To deactivate, run: deactivate"
echo ""
