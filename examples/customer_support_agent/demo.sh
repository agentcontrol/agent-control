#!/bin/bash
#
# Customer Support Agent Demo - Setup & Teardown Script
#
# Usage:
#   ./demo.sh start     Start all services (database, server, UI)
#   ./demo.sh stop      Stop all services
#   ./demo.sh reset     Reset database and stop services
#   ./demo.sh status    Check status of services
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVER_DIR="$ROOT_DIR/server"
UI_DIR="$ROOT_DIR/ui"

# PID files for tracking background processes
SERVER_PID_FILE="/tmp/agent-control-server.pid"
UI_PID_FILE="/tmp/agent-control-ui.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}==>${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}Warning:${NC} $1"
}

print_error() {
    echo -e "${RED}Error:${NC} $1"
}

check_dependencies() {
    local missing=()

    if ! command -v docker &> /dev/null; then
        missing+=("docker")
    fi

    if ! command -v python &> /dev/null; then
        missing+=("python")
    fi

    if ! command -v pnpm &> /dev/null; then
        missing+=("pnpm")
    fi

    if [ ${#missing[@]} -ne 0 ]; then
        print_error "Missing dependencies: ${missing[*]}"
        exit 1
    fi
}

start_database() {
    print_status "Starting database..."
    cd "$SERVER_DIR"
    docker compose up -d

    # Wait for database to be ready
    print_status "Waiting for database to be ready..."
    for i in {1..30}; do
        if docker compose exec -T postgres pg_isready -U agent_control -d agent_control &> /dev/null; then
            print_status "Database is ready"
            return 0
        fi
        sleep 1
    done
    print_error "Database failed to start"
    exit 1
}

stop_database() {
    print_status "Stopping database..."
    cd "$SERVER_DIR"
    docker compose down
}

run_migrations() {
    print_status "Running database migrations..."
    cd "$SERVER_DIR"
    make alembic-upgrade
}

start_server() {
    print_status "Starting server..."
    cd "$SERVER_DIR"

    # Check if server is already running
    if [ -f "$SERVER_PID_FILE" ] && kill -0 "$(cat "$SERVER_PID_FILE")" 2>/dev/null; then
        print_warning "Server is already running (PID: $(cat "$SERVER_PID_FILE"))"
        return 0
    fi

    # Start server in background
    uv run --package agent-control-server uvicorn agent_control_server.main:app --reload &> /tmp/agent-control-server.log &
    echo $! > "$SERVER_PID_FILE"

    # Wait for server to be ready
    print_status "Waiting for server to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:8000/health &> /dev/null; then
            print_status "Server is ready at http://localhost:8000"
            return 0
        fi
        sleep 1
    done
    print_error "Server failed to start. Check /tmp/agent-control-server.log"
    exit 1
}

stop_server() {
    print_status "Stopping server..."
    if [ -f "$SERVER_PID_FILE" ]; then
        local pid=$(cat "$SERVER_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            # Also kill any child processes (uvicorn workers)
            pkill -P "$pid" 2>/dev/null || true
        fi
        rm -f "$SERVER_PID_FILE"
    fi
    # Kill any remaining uvicorn processes for this project
    pkill -f "uvicorn agent_control_server.main:app" 2>/dev/null || true
}

start_ui() {
    print_status "Starting UI..."
    cd "$UI_DIR"

    # Check if UI is already running
    if [ -f "$UI_PID_FILE" ] && kill -0 "$(cat "$UI_PID_FILE")" 2>/dev/null; then
        print_warning "UI is already running (PID: $(cat "$UI_PID_FILE"))"
        return 0
    fi

    # Install dependencies if needed
    if [ ! -d "node_modules" ]; then
        print_status "Installing UI dependencies..."
        pnpm install
    fi

    # Start UI in background
    pnpm dev &> /tmp/agent-control-ui.log &
    echo $! > "$UI_PID_FILE"

    # Wait for UI to be ready
    print_status "Waiting for UI to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:4000 &> /dev/null; then
            print_status "UI is ready at http://localhost:4000"
            return 0
        fi
        sleep 1
    done
    print_warning "UI may still be starting. Check /tmp/agent-control-ui.log"
}

stop_ui() {
    print_status "Stopping UI..."
    if [ -f "$UI_PID_FILE" ]; then
        local pid=$(cat "$UI_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            pkill -P "$pid" 2>/dev/null || true
        fi
        rm -f "$UI_PID_FILE"
    fi
    # Kill any remaining next.js processes for this project
    pkill -f "next dev.*4000" 2>/dev/null || true
}

reset_database() {
    print_status "Resetting database..."
    cd "$SERVER_DIR"

    # Stop the container and remove the volume
    docker compose down -v

    print_status "Database volume deleted"
}

show_status() {
    echo ""
    echo "Service Status:"
    echo "---------------"

    # Database
    cd "$SERVER_DIR"
    if docker compose ps 2>/dev/null | grep -q "postgres.*running"; then
        echo -e "Database:  ${GREEN}Running${NC}"
    else
        echo -e "Database:  ${RED}Stopped${NC}"
    fi

    # Server
    if curl -s http://localhost:8000/health &> /dev/null; then
        echo -e "Server:    ${GREEN}Running${NC} (http://localhost:8000)"
    else
        echo -e "Server:    ${RED}Stopped${NC}"
    fi

    # UI
    if curl -s http://localhost:4000 &> /dev/null; then
        echo -e "UI:        ${GREEN}Running${NC} (http://localhost:4000)"
    else
        echo -e "UI:        ${RED}Stopped${NC}"
    fi

    echo ""
}

setup_demo_controls() {
    print_status "Setting up demo agent and controls..."
    cd "$SCRIPT_DIR"
    python setup_demo_controls.py
}

# Agent name used by the demo (must match support_agent.py)
get_agent_name() {
    echo "646d5dea-c2e6-4453-b446-7035482b38e4"
}

show_observability_stats() {
    local agent_name=$(get_agent_name)
    local server_url="${AGENT_CONTROL_URL:-http://localhost:8000}"

    echo ""
    echo "========================================"
    echo "  Observability Stats"
    echo "========================================"
    echo ""

    # Check if server is running
    if ! curl -s "${server_url}/health" &> /dev/null; then
        print_warning "Server not running - cannot fetch stats"
        return
    fi

    # Fetch stats for 5 minutes
    echo "Last 5 minutes:"
    echo "---------------"
    local stats_5m=$(curl -s "${server_url}/api/v1/observability/stats?agent_name=${agent_name}&time_range=5m")
    if echo "$stats_5m" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"  Total executions: {d.get('total_executions', 0)}\"); print(f\"  Matches: {d.get('total_matches', 0)}\"); print(f\"  Non-matches: {d.get('total_non_matches', 0)}\"); print(f\"  Errors: {d.get('total_errors', 0)}\"); actions=d.get('action_counts', {}); print(f\"  Actions: allow={actions.get('allow', 0)}, deny={actions.get('deny', 0)}, warn={actions.get('warn', 0)}, log={actions.get('log', 0)}\")" 2>/dev/null; then
        :
    else
        echo "  No data or error fetching stats"
    fi

    echo ""

    # Fetch stats for 1 hour (closest to 30 mins available)
    echo "Last 1 hour:"
    echo "------------"
    local stats_1h=$(curl -s "${server_url}/api/v1/observability/stats?agent_name=${agent_name}&time_range=1h")
    if echo "$stats_1h" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f\"  Total executions: {d.get('total_executions', 0)}\"); print(f\"  Matches: {d.get('total_matches', 0)}\"); print(f\"  Non-matches: {d.get('total_non_matches', 0)}\"); print(f\"  Errors: {d.get('total_errors', 0)}\"); actions=d.get('action_counts', {}); print(f\"  Actions: allow={actions.get('allow', 0)}, deny={actions.get('deny', 0)}, warn={actions.get('warn', 0)}, log={actions.get('log', 0)}\")" 2>/dev/null; then
        :
    else
        echo "  No data or error fetching stats"
    fi

    echo ""

    # Show per-control breakdown if there are any executions
    if echo "$stats_1h" | python3 -c "import sys, json; d=json.load(sys.stdin); exit(0 if d.get('total_executions', 0) > 0 else 1)" 2>/dev/null; then
        echo "Per-control breakdown (last 1 hour):"
        echo "------------------------------------"
        echo "$stats_1h" | python3 -c "
import sys, json
d = json.load(sys.stdin)
controls = d.get('controls', [])
if controls:
    for c in controls:
        name = c.get('control_name', 'Unknown')[:30]
        execs = c.get('execution_count', 0)
        matches = c.get('match_count', 0)
        print(f\"  {name:<32} execs={execs:<4} matches={matches}\")
else:
    print('  No control executions yet')
" 2>/dev/null || echo "  Unable to parse control stats"
    fi

    echo ""
}

cmd_start() {
    check_dependencies

    echo ""
    echo "========================================"
    echo "  Customer Support Agent Demo - Start"
    echo "========================================"
    echo ""

    start_database
    run_migrations
    start_server
    start_ui
    setup_demo_controls

    echo ""
    echo "========================================"
    echo "  Ready to demo!"
    echo "========================================"
    echo ""
    echo "The agent is registered with demo controls."
    echo ""
    echo "Demo controls configured:"
    echo "  • LLM controls: path selectors (input, output)"
    echo "  • Tool controls: tool_names (exact match)"
    echo "  • Tool controls: tool_name_regex (pattern match)"
    echo "  • Nested path selectors: arguments.query, arguments.priority"
    echo ""
    echo "Next steps:"
    echo "  1. Open the UI:   http://localhost:4000"
    echo "     (You'll see the agent with controls already configured)"
    echo ""
    echo "  2. Run the demo:  python $SCRIPT_DIR/run_demo.py"
    echo "     Try: /test-multispan, /test-tool-controls, /comprehensive"
    echo ""
    echo "  3. View stats:    $0 stats"
    echo "     (Shows observability stats for last 5m and 1h)"
    echo ""
    echo "To stop all services:  $0 stop"
    echo ""
}

cmd_stop() {
    echo ""
    echo "========================================"
    echo "  Customer Support Agent Demo - Stop"
    echo "========================================"
    echo ""

    stop_ui
    stop_server
    stop_database

    echo ""
    print_status "All services stopped"
    echo ""
}

cmd_reset() {
    echo ""
    echo "========================================"
    echo "  Customer Support Agent Demo - Reset"
    echo "========================================"
    echo ""
    print_warning "This will delete the database and all data!"
    echo ""
    read -p "Are you sure you want to reset? (y/N) " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        stop_ui
        stop_server
        reset_database

        echo ""
        print_status "Reset complete. Run '$0 start' to start fresh."
        echo ""
    else
        echo "Reset cancelled."
    fi
}

# Main command handler
case "${1:-}" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    reset)
        cmd_reset
        ;;
    status)
        show_status
        ;;
    stats)
        show_observability_stats
        ;;
    *)
        echo "Customer Support Agent Demo"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  start   Start all services (database, server, UI)"
        echo "  stop    Stop all services"
        echo "  reset   Reset database and stop services (with confirmation)"
        echo "  status  Check status of services"
        echo "  stats   Show observability stats (last 5m and 1h)"
        echo ""
        exit 1
        ;;
esac
