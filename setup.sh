#!/bin/bash
set -e

# Agent Control UV Environment Setup Script
# This script automates the setup of all workspaces

echo "=================================================="
echo "  Agent Control - UV Environment Setup"
echo "=================================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${RED}✗ UV is not installed${NC}"
    echo ""
    echo "Install UV with:"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓ UV is installed: $(uv --version)${NC}"
echo ""

# Function to setup a workspace
setup_workspace() {
    local dir=$1
    local name=$2
    
    echo -e "${BLUE}Setting up $name...${NC}"
    cd "$dir"
    
    if uv sync; then
        echo -e "${GREEN}✓ $name installed successfully${NC}"
    else
        echo -e "${RED}✗ Failed to install $name${NC}"
        exit 1
    fi
    
    cd - > /dev/null
    echo ""
}

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Project root: $SCRIPT_DIR"
echo ""

# Setup each workspace
echo "=================================================="
echo "  Installing Workspaces"
echo "=================================================="
echo ""

setup_workspace "models" "Models Package"
setup_workspace "server" "Server Workspace"
setup_workspace "sdks" "SDKs Workspace"

# Verify installations
echo "=================================================="
echo "  Verifying Installations"
echo "=================================================="
echo ""

echo -e "${BLUE}Verifying models...${NC}"
if cd models && uv run python -c "from agent_control_models import Agent; print('✓ Models OK')" 2>/dev/null; then
    echo -e "${GREEN}✓ Models verified${NC}"
else
    echo -e "${YELLOW}⚠ Models import failed (may need to check dependencies)${NC}"
fi
cd "$SCRIPT_DIR"
echo ""

echo -e "${BLUE}Verifying server...${NC}"
if cd server && uv run python -c "from agent_control_server.main import app; print('✓ Server OK')" 2>/dev/null; then
    echo -e "${GREEN}✓ Server verified${NC}"
else
    echo -e "${YELLOW}⚠ Server import failed (may need to check dependencies)${NC}"
fi
cd "$SCRIPT_DIR"
echo ""

echo -e "${BLUE}Verifying SDK...${NC}"
if cd sdks && uv run python -c "from agent_control import AgentControlClient; print('✓ SDK OK')" 2>/dev/null; then
    echo -e "${GREEN}✓ SDK verified${NC}"
else
    echo -e "${YELLOW}⚠ SDK import failed (may need to check dependencies)${NC}"
fi
cd "$SCRIPT_DIR"
echo ""

echo "=================================================="
echo "  Setup Complete!"
echo "=================================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Start the server:"
echo "   ${GREEN}cd server${NC}"
echo "   ${GREEN}uv run uvicorn agent_control_server.main:app --reload${NC}"
echo ""
echo "2. Test the SDK (in another terminal):"
echo "   ${GREEN}cd examples${NC}"
echo "   ${GREEN}export PYTHONPATH=\"\${PYTHONPATH}:\$(pwd)/../sdks/python/src\"${NC}"
echo "   ${GREEN}python basic_usage.py${NC}"
echo ""
echo "3. Run LangGraph example:"
echo "   ${GREEN}cd examples/customer_support_agent${NC}"
echo "   ${GREEN}uv sync${NC}"
echo "   ${GREEN}uv run python run_demo.py${NC}"
echo ""
echo "For more details, see:"
echo "  - ${BLUE}UV_SETUP_GUIDE.md${NC} - Complete UV guide"
echo "  - ${BLUE}SETUP.md${NC} - Project setup guide"
echo "  - ${BLUE}QUICKSTART.md${NC} - Quick start guide"
echo ""

