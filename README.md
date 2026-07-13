# NetTwin AI

NetTwin AI is a unified GNS3 automation and network change impact analysis platform.

Sprint 0 provides the initial repository architecture, environment configuration, backend/frontend placeholders, and documentation required to start implementation without coupling business logic too early.

## Planned Workflow

```text
User Requirement
  -> Topology Specification
  -> IP Address Planning
  -> GNS3 Deployment
  -> Configuration Generation
  -> Configuration Application
  -> Network Validation
  -> Digital Network Model
  -> Proposed Change Simulation
  -> Impact and Risk Analysis
  -> User Approval
  -> Apply Change to GNS3
  -> Post-Change Verification
  -> Rollback or Final Report
```

## Repository Layout

```text
backend/
  app/
  tests/
frontend/
  src/
docs/
templates/
examples/
```

## Backend Modules

- `domain`: vendor-neutral network domain model and business rules
- `topology`: topology parsing and normalization
- `addressing`: IP planning and VLSM logic
- `gns3`: GNS3 REST/WebSocket integration
- `configuration`: configuration rendering and diffing
- `discovery`: running-state collection and parsing
- `graph`: connectivity and dependency graph services
- `validation`: test execution and topology validation
- `changes`: change commands and workflows
- `simulation`: isolated change simulation engine
- `impact`: impact detection and risk scoring
- `rollback`: rollback planning and execution
- `reporting`: reports, audits, and exports
- `ai`: structured LLM integration layer
- `api`: FastAPI transport layer

## Quick Start

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
uvicorn app.main:app --reload
```

API health check:

```powershell
curl http://127.0.0.1:8000/health
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

### GNS3 Connectivity Check

```powershell
curl http://localhost:3080/v2/version
```

## Sprint 0 Deliverables

- initial backend architecture
- initial frontend placeholder
- environment and logging configuration
- architecture documentation
- Mermaid system diagram
- basic automated tests
- repository scaffolding for later sprints

## Documentation

- [Architecture](docs/architecture.md)

## Current Status

This repository intentionally avoids full business logic in Sprint 0. The goal is modularity, separation of concerns, extensibility, and testability.

