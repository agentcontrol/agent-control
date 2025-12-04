# Deployment Architecture

How Agent Protect components are deployed in a production environment.

## Kubernetes Deployment

```mermaid
flowchart TB
    subgraph k8s["Kubernetes Cluster"]
        subgraph ns["agent-control namespace"]
            subgraph deploy["Deployment: agent-control-server"]
                pod1["Pod"]
                pod2["Pod"]
                pod3["Pod"]
            end
            
            svc["Service<br/>agent-control-server"]
            hpa["HPA<br/>Auto-scaling"]
            
            subgraph db["StatefulSet or Managed"]
                pg[(PostgreSQL)]
            end
        end
        
        ing["Ingress Controller"]
    end

    subgraph apps["Client Applications"]
        app1["Agent App 1"]
        app2["Agent App 2"]
        app3["Agent App N"]
    end

    apps --> ing
    ing --> svc
    svc --> deploy
    deploy --> pg
    hpa -.->|scales| deploy
```

## Service Communication

```mermaid
flowchart LR
    subgraph external["External"]
        client["SDK Client"]
    end

    subgraph cluster["Kubernetes"]
        ingress["Ingress<br/>:443"]
        service["Service<br/>:8000"]
        
        subgraph pods["Pods"]
            uvicorn1["Uvicorn<br/>:8000"]
            uvicorn2["Uvicorn<br/>:8000"]
        end
        
        postgres[(PostgreSQL<br/>:5432)]
    end

    client -->|HTTPS| ingress
    ingress -->|HTTP| service
    service -->|Round Robin| pods
    pods -->|TCP| postgres
```

## Configuration

```mermaid
flowchart TD
    subgraph config["Configuration Sources"]
        env["Environment Variables<br/>━━━━━━━━━━━━━━━<br/>DATABASE_URL<br/>API_PREFIX<br/>DEBUG"]
        
        secrets["Kubernetes Secrets<br/>━━━━━━━━━━━━━━━<br/>DB credentials<br/>API keys"]
        
        configmap["ConfigMap<br/>━━━━━━━━━━━━━━━<br/>Feature flags<br/>Plugin configs"]
    end

    subgraph server["Server Pod"]
        app["Agent Control Server"]
    end

    env --> app
    secrets --> app
    configmap --> app
```

## Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/health` | GET | Liveness/readiness probe |
| `/api/v1/agents/*` | * | Agent management |
| `/api/v1/policies/*` | * | Policy management |
| `/api/v1/control-sets/*` | * | Control set management |
| `/api/v1/controls/*` | * | Control management |
| `/api/v1/evaluation` | POST | Control evaluation |
