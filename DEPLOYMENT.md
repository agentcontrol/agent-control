# Deployment Guide

This guide covers how to deploy the Agent Protect server and SDK independently.

## Architecture Overview

```
agent-protect/
├── models/          # Shared data models (dependency for both)
├── server/          # FastAPI server application (separate workspace)
└── sdks/            # SDKs workspace
    └── python/      # Python SDK implementation
```

The project uses a **multi-workspace structure** with **path-based dependencies**:
- `models` is the foundation, containing all shared Pydantic models
- `server` has its own workspace and references `models` via path
- `sdks` has its own workspace and references `models` via path
- Each workspace can be developed and deployed independently

## Prerequisites

- Python 3.11+
- `uv` package manager installed
- For server deployment: Access to a server/cloud platform
- For SDK publishing: PyPI account (optional)

## Development Setup

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/agent-protect.git
cd agent-protect

# Install server dependencies
cd server
uv sync

# Install SDK dependencies
cd ../sdks
uv sync

# Each workspace manages its own dependencies and references models via path
```

### Running Locally

#### Run the Server

```bash
# Option 1: Using Python module
cd server
uv run python -m agent_control_server.main

# Option 2: Using the installed command
uv run agent-control-server

# Option 3: For development with auto-reload
uv run uvicorn agent_control_server.main:app --reload --host 0.0.0.0 --port 8000
```

#### Test the SDK

```bash
# Create a test script
cat > test_sdk.py << 'EOF'
import asyncio
from agent_protect import AgentProtectClient

async def main():
    async with AgentProtectClient(base_url="http://localhost:8000") as client:
        # Health check
        health = await client.health_check()
        print(f"Server: {health}")
        
        # Protection check
        result = await client.check_protection("Hello, world!")
        print(f"Result: {result}")
        print(f"Is safe: {result.is_safe}")
        print(f"Confident: {result.is_confident()}")

asyncio.run(main())
EOF

# Run it
uv run python test_sdk.py
```

## Independent Deployment

### Deploying the Models Package

The models package should be deployed first since both server and SDK depend on it.

#### Option 1: Publish to PyPI

```bash
cd models

# Build the package
uv build

# Publish to PyPI (requires PyPI account)
uv publish

# Or use twine
pip install twine
twine upload dist/*
```

#### Option 2: Private Package Repository

```bash
cd models
uv build

# Upload to your private repository (e.g., AWS CodeArtifact, JFrog Artifactory)
# Example with AWS CodeArtifact:
aws codeartifact login --tool twine --repository my-repo --domain my-domain
twine upload --repository codeartifact dist/*
```

#### Option 3: Install from Git (Development)

```bash
# Install directly from git
pip install git+https://github.com/yourusername/agent-protect.git#subdirectory=models

# Or from a specific branch/tag
pip install git+https://github.com/yourusername/agent-protect.git@v0.1.0#subdirectory=models
```

### Deploying the Server

#### Option 1: Docker Deployment (Recommended)

Create `server/Dockerfile`:

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Configure uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy workspace files
COPY pyproject.toml uv.lock* ./
COPY models/ models/
COPY engine/ engine/
COPY server/ server/

# Install
RUN uv sync --package agent-control-server --no-dev

# Path
ENV PATH="/app/.venv/bin:$PATH"
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["agent-control-server"]
```

Build and run:

```bash
# Build from root
docker build -t agent-control-server:latest -f server/Dockerfile .

# Run locally
docker run -p 8000:8000 agent-control-server:latest
```

#### Option 2: Cloud Platform (AWS/GCP/Azure)

**AWS Elastic Beanstalk:**

```bash
cd server

# Create requirements.txt from uv
uv pip compile pyproject.toml -o requirements.txt

# Create Procfile
echo "web: agent-protect-server" > Procfile

# Deploy
eb init -p python-3.11 agent-protect
eb create agent-protect-env
eb deploy
```

**Google Cloud Run:**

```bash
# Build with Cloud Build
gcloud builds submit --tag gcr.io/PROJECT-ID/agent-protect-server server/

# Deploy
gcloud run deploy agent-protect-server \
  --image gcr.io/PROJECT-ID/agent-protect-server \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

**Azure Container Instances:**

```bash
# Build and push
docker build -t agent-protect-server:latest -f server/Dockerfile .
docker tag agent-protect-server:latest yourregistry.azurecr.io/agent-protect-server:latest
docker push yourregistry.azurecr.io/agent-protect-server:latest

# Deploy
az container create \
  --resource-group myResourceGroup \
  --name agent-protect-server \
  --image yourregistry.azurecr.io/agent-protect-server:latest \
  --dns-name-label agent-protect \
  --ports 8000
```

#### Option 3: Kubernetes

Create `server/k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-protect-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: agent-protect-server
  template:
    metadata:
      labels:
        app: agent-protect-server
    spec:
      containers:
      - name: server
        image: your-registry/agent-protect-server:latest
        ports:
        - containerPort: 8000
        env:
        - name: HOST
          value: "0.0.0.0"
        - name: PORT
          value: "8000"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: agent-protect-server
spec:
  selector:
    app: agent-protect-server
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

Deploy:

```bash
kubectl apply -f server/k8s-deployment.yaml
```

#### Option 4: Traditional Server (systemd)

```bash
# On the server
cd /opt/agent-protect

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/yourusername/agent-protect.git
cd agent-protect

# Install models
cd models && uv build && pip install dist/*.whl && cd ..

# Install server
cd server && pip install -e . && cd ..

# Create systemd service
sudo tee /etc/systemd/system/agent-protect-server.service << EOF
[Unit]
Description=Agent Protect Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/agent-protect/server
ExecStart=/usr/local/bin/agent-protect-server
Restart=always
Environment="HOST=0.0.0.0"
Environment="PORT=8000"

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl daemon-reload
sudo systemctl enable agent-protect-server
sudo systemctl start agent-protect-server
```

### Deploying the SDK

#### Option 1: Publish to PyPI (Public)

```bash
# Ensure models is published first
cd models
uv build
uv publish

# Now publish the SDK
cd ../sdks/python

# Update pyproject.toml to use PyPI version
# Remove [tool.uv.sources] section
# Change dependency to: "agent-protect-models>=0.1.0"

# Build and publish
uv build
uv publish
```

#### Option 2: Publish to Private PyPI

```bash
cd sdks/python

# Build
uv build

# Publish to private repository
uv publish --repository-url https://your-private-pypi.com/simple/

# Or with twine
pip install twine
twine upload --repository-url https://your-private-pypi.com/simple/ dist/*
```

#### Option 3: Install from Git

Users can install directly from your repository:

```bash
# Install the SDK (with models as dependency)
pip install git+https://github.com/yourusername/agent-protect.git#subdirectory=sdks/python
```

#### Option 4: Distribute Wheels Directly

```bash
cd sdks/python
uv build

# Distribute dist/agent_protect-0.1.0-py3-none-any.whl
# Users install with:
pip install agent_protect-0.1.0-py3-none-any.whl
```

## Environment Configuration

### Server Configuration

Create `.env` file in server directory:

```env
# Server settings
HOST=0.0.0.0
PORT=8000
DEBUG=false

# API settings
API_VERSION=v1
API_PREFIX=/api

# Add your custom settings here
DATABASE_URL=postgresql://user:pass@localhost/dbname
REDIS_URL=redis://localhost:6379
```

### SDK Configuration

SDK users configure via code:

```python
from agent_protect import AgentProtectClient

# Development
client = AgentProtectClient(base_url="http://localhost:8000")

# Production
client = AgentProtectClient(
    base_url="https://api.yourcompany.com",
    timeout=60.0
)
```

## Versioning Strategy

### Semantic Versioning

All packages follow SemVer (MAJOR.MINOR.PATCH):

- **MAJOR**: Breaking changes (API contract changes)
- **MINOR**: New features (backwards compatible)
- **PATCH**: Bug fixes (backwards compatible)

### Version Compatibility

```
models v0.1.0  ← server v0.1.0  ← sdk v0.1.0
       ↓              ↓              ↓
models v0.2.0  ← server v0.2.0  ← sdk v0.2.0
```

Rules:
1. **Models** versions should be tagged and released first
2. **Server** can use models of same or older MINOR version
3. **SDK** should match models version exactly for type safety
4. When updating models, update both server and SDK

### Release Process

```bash
# 1. Update version in models/pyproject.toml
# 2. Build and publish models
cd models
uv build
uv publish
git tag models-v0.1.0
git push origin models-v0.1.0

# 3. Update server to use new models version
cd ../server
# Update pyproject.toml: agent-protect-models>=0.1.0
uv sync
uv build
git tag server-v0.1.0
git push origin server-v0.1.0

# 4. Update and publish SDK
cd ../sdks/python
# Update pyproject.toml: agent-protect-models>=0.1.0
uv sync
uv build
uv publish
git tag sdk-v0.1.0
git push origin sdk-v0.1.0
```

## CI/CD Pipeline Example

### GitHub Actions

Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    tags:
      - 'models-v*'
      - 'server-v*'
      - 'sdk-v*'

jobs:
  deploy-models:
    if: startsWith(github.ref, 'refs/tags/models-v')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v1
      - name: Build and publish models
        run: |
          cd models
          uv build
          uv publish --token ${{ secrets.PYPI_TOKEN }}

  deploy-server:
    if: startsWith(github.ref, 'refs/tags/server-v')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t agent-protect-server:${{ github.ref_name }} -f server/Dockerfile .
      - name: Push to registry
        run: |
          echo ${{ secrets.DOCKER_PASSWORD }} | docker login -u ${{ secrets.DOCKER_USERNAME }} --password-stdin
          docker push agent-protect-server:${{ github.ref_name }}

  deploy-sdk:
    if: startsWith(github.ref, 'refs/tags/sdk-v')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v1
      - name: Build and publish SDK
        run: |
          cd sdks/python
          uv build
          uv publish --token ${{ secrets.PYPI_TOKEN }}
```

## Monitoring and Health Checks

### Server Health Check

```bash
# Check if server is running
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy","version":"0.1.0"}
```

### SDK Health Check

```python
import asyncio
from agent_protect import AgentProtectClient

async def check():
    try:
        async with AgentProtectClient(base_url="http://your-server.com") as client:
            health = await client.health_check()
            print(f"✓ Server is healthy: {health}")
            return True
    except Exception as e:
        print(f"✗ Server is down: {e}")
        return False

asyncio.run(check())
```

## Troubleshooting

### Common Issues

**Problem**: `ModuleNotFoundError: No module named 'agent_control_models'`

**Solution**: Install models package first or ensure workspace dependencies are set up correctly.

```bash
cd models && uv build && pip install dist/*.whl
```

**Problem**: SDK can't connect to server

**Solution**: Check server is running and URL is correct:

```bash
curl http://localhost:8000/health
```

**Problem**: Version mismatch between packages

**Solution**: Ensure all packages use compatible versions:

```bash
pip list | grep agent-protect
```

## Best Practices

1. **Always deploy models first** before server or SDK
2. **Use semantic versioning** for all releases
3. **Test in staging** before production deployment
4. **Monitor health endpoints** after deployment
5. **Keep SDK and server versions in sync** for best compatibility
6. **Use environment variables** for configuration, never hardcode
7. **Enable logging** in production for debugging
8. **Set up alerting** on health check failures
9. **Use CI/CD** for automated, reliable deployments
10. **Document API changes** in CHANGELOG.md

## Support

For deployment issues, check:
- Server logs: `journalctl -u agent-protect-server -f`
- Docker logs: `docker logs agent-protect-server`
- Health endpoint: `curl http://your-server/health`

