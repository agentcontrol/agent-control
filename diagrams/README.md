# Agent Protect Architecture Diagrams

This folder contains architecture diagrams for the Agent Protect system. All diagrams use Mermaid syntax and render natively in GitHub.

## Diagram Index

### High-Level Architecture
| Diagram | Description | Audience |
|---------|-------------|----------|
| [01-system-overview.md](./01-system-overview.md) | Bird's eye view of the entire system | Everyone |
| [02-deployment-architecture.md](./02-deployment-architecture.md) | How components are deployed | DevOps, Backend |

### Data Models
| Diagram | Description | Audience |
|---------|-------------|----------|
| [03-entity-relationships.md](./03-entity-relationships.md) | Database schema and relationships | Backend |
| [04-control-definition-model.md](./04-control-definition-model.md) | Control configuration structure | Backend, SDK Users |
| [05-request-response-models.md](./05-request-response-models.md) | API request/response schemas | SDK Users |

### Flows & Sequences
| Diagram | Description | Audience |
|---------|-------------|----------|
| [06-evaluation-flow.md](./06-evaluation-flow.md) | How controls are evaluated | Backend |
| [07-agent-lifecycle.md](./07-agent-lifecycle.md) | Agent registration and policy assignment | SDK Users |
| [08-protect-decorator-flow.md](./08-protect-decorator-flow.md) | How @protect decorator works | SDK Users |

### Component Deep Dives
| Diagram | Description | Audience |
|---------|-------------|----------|
| [09-plugin-system.md](./09-plugin-system.md) | External evaluator integration | Backend, Plugin Authors |
| [10-sdk-architecture.md](./10-sdk-architecture.md) | Python SDK module structure | SDK Users |

## Viewing Diagrams

### GitHub
Mermaid diagrams render automatically when viewing markdown files on GitHub.

### VS Code
Install the "Markdown Preview Mermaid Support" extension.

### Local
Use the Mermaid CLI or online editor at https://mermaid.live
