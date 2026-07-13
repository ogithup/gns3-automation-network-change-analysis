# NetTwin AI

NetTwin AI is a unified GNS3 automation and network change impact analysis platform.

Sprint 0 established the repository architecture, environment configuration, backend/frontend placeholders, and project documentation.

Sprint 1 adds the vendor-neutral topology domain model, YAML/JSON parsing, topology validation, and example network specifications.

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
Invoke-WebRequest http://[::1]:3080/v2/version -UseBasicParsing
```

## Sprint 0 Deliverables

- initial backend architecture
- initial frontend placeholder
- environment and logging configuration
- architecture documentation
- Mermaid system diagram
- basic automated tests
- repository scaffolding for later sprints

## Sprint 1 Deliverables

- vendor-neutral `TopologySpec`
- Pydantic domain models for network objects
- YAML and JSON topology parsing
- topology validation engine
- three example topology specifications
- topology parser and validation tests

## Sprint 1 Usage

### Run Backend Tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest
```

### Run Only Sprint 1 Topology Tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest tests/test_topology_service.py -q
```

### Validate an Example Topology File

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "from pathlib import Path; from app.topology.service import TopologyService; spec = TopologyService.load_file(Path('..') / 'examples' / 'three-vlan-office.yaml'); print(spec.project.name, len(spec.devices), len(spec.vlans))"
```

Expected output:

```text
three-vlan-office 5 3
```

### Test JSON Serialization Round-Trip

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "from pathlib import Path; from app.topology.service import TopologyService; spec = TopologyService.load_file(Path('..') / 'examples' / 'guest-isolation.yaml'); serialized = TopologyService.to_json(spec); restored = TopologyService.load_json(serialized); print(restored.project.name)"
```

Expected output:

```text
guest-isolation
```

## Example Topologies

- `examples/three-vlan-office.yaml`
- `examples/two-router-ospf.yaml`
- `examples/guest-isolation.yaml`

## Documentation

- [Architecture](docs/architecture.md)

## Current Status

Current implementation includes:

- Sprint 0 project scaffolding
- Sprint 1 topology domain model and validation

Business logic for GNS3 deployment, configuration application, discovery, simulation, and impact analysis is still deferred to later sprints.
