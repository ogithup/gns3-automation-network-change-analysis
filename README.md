# NetTwin AI

NetTwin AI is a unified GNS3 automation and network change impact analysis platform.

Sprint 0 established the repository architecture, environment configuration, backend/frontend placeholders, and project documentation.

Sprint 1 adds the vendor-neutral topology domain model, YAML/JSON parsing, topology validation, and example network specifications.

Sprint 2 adds the IPv4 addressing and VLSM planning engine, including reserved ranges, fixed subnet handling, point-to-point allocation, and explainable address planning output.

Sprint 3 adds the asynchronous GNS3 API client, template resolution, project/node/link resource management, and mocked deployment orchestration tests.

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

## Sprint 2 Deliverables

- deterministic IPv4 VLSM planner
- reserved subnet support
- fixed subnet support
- point-to-point /30 and /31 allocation
- gateway, switch management, and endpoint address assignment
- explainable address planning report
- automated tests for exhaustion, overlap, and mixed requirements

## Sprint 2 Usage

### Run All Backend Tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest
```

### Run Only Sprint 2 Addressing Tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest tests/test_addressing_service.py -q
```

### Generate a VLSM Plan from the Terminal

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "from ipaddress import IPv4Network; from app.addressing.models import AddressingRequest, SegmentRequirement; from app.addressing.service import AddressingService; request = AddressingRequest(base_network=IPv4Network('10.10.0.0/16'), segments=[SegmentRequirement(name='ADMIN', host_count=40), SegmentRequirement(name='STUDENT', host_count=200), SegmentRequirement(name='GUEST', host_count=100)]); plan = AddressingService.plan(request); print(plan.report)"
```

Expected key allocations:

```text
STUDENT -> 10.10.0.0/24
GUEST -> 10.10.1.0/25
ADMIN -> 10.10.1.128/26
```

### Validate Reserved and Fixed Subnet Behavior

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "from ipaddress import IPv4Network; from app.addressing.models import AddressingRequest, SegmentRequirement; from app.addressing.service import AddressingService; request = AddressingRequest(base_network=IPv4Network('10.20.0.0/24'), reserved_networks=[IPv4Network('10.20.0.0/26')], segments=[SegmentRequirement(name='VOICE', host_count=20, fixed_subnet=IPv4Network('10.20.0.128/27'))]); plan = AddressingService.plan(request); print(plan.allocations[0].network)"
```

Expected output:

```text
10.20.0.128/27
```

### Try Different Host Inputs

If the user enters different host counts, the planner recalculates a new subnet plan. Example:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "from ipaddress import IPv4Network; from app.addressing.models import AddressingRequest, SegmentRequirement; from app.addressing.service import AddressingService; request = AddressingRequest(base_network=IPv4Network('192.168.0.0/24'), segments=[SegmentRequirement(name='HR', host_count=20), SegmentRequirement(name='IT', host_count=50), SegmentRequirement(name='SALES', host_count=10)]); plan = AddressingService.plan(request); print(plan.report)"
```

Another example with larger requirements:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "from ipaddress import IPv4Network; from app.addressing.models import AddressingRequest, SegmentRequirement; from app.addressing.service import AddressingService; request = AddressingRequest(base_network=IPv4Network('172.16.0.0/20'), segments=[SegmentRequirement(name='VLAN10', host_count=400), SegmentRequirement(name='VLAN20', host_count=100), SegmentRequirement(name='VLAN30', host_count=60), SegmentRequirement(name='VLAN40', host_count=12)]); plan = AddressingService.plan(request); print(plan.report)"
```

### Test Address Exhaustion

If the requested hosts do not fit inside the base network, the planner must fail with an `AddressPlanningError`:

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "from ipaddress import IPv4Network; from app.addressing.models import AddressingRequest, SegmentRequirement; from app.addressing.service import AddressingService; request = AddressingRequest(base_network=IPv4Network('192.168.1.0/29'), segments=[SegmentRequirement(name='LAB', host_count=10)]); print(AddressingService.plan(request).report)"
```

## Documentation

- [Architecture](docs/architecture.md)

## Sprint 3 Deliverables

- async `GNS3Client` built on `httpx.AsyncClient`
- GNS3 project lifecycle service
- template resolver for `iosv`, `iosvl2`, `vpcs`, and related logical names
- node and link management services
- deployment orchestrator with rollback on partial failure
- dry-run deployment planning
- mocked API tests for version, templates, deployment, and rollback

## Sprint 3 Usage

### Verify GNS3 Connectivity Before Tests

```powershell
Invoke-WebRequest http://[::1]:3080/v2/version -UseBasicParsing
Invoke-WebRequest http://[::1]:3080/v2/projects -UseBasicParsing
Invoke-WebRequest http://[::1]:3080/v2/templates -UseBasicParsing
```

### Run Only Sprint 3 GNS3 Tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -e .[dev]
pytest tests/test_gns3_client.py -q
```

### Inspect Available GNS3 Templates

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "import asyncio; from app.gns3.client import GNS3Client; async def main():\n    async with GNS3Client() as client:\n        templates = await client.list_templates();\n        print([(template.name, template.template_id) for template in templates]);\nasyncio.run(main())"
```

### Resolve a Logical Platform Name

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "import asyncio; from app.gns3.client import GNS3Client; from app.gns3.services import GNS3TemplateResolver; async def main():\n    async with GNS3Client() as client:\n        resolver = GNS3TemplateResolver(client); template = await resolver.resolve('iosv'); print(template.name, template.template_id)\nasyncio.run(main())"
```

### Retrieve GNS3 Server Version Through the Backend Client

```powershell
cd backend
.venv\Scripts\Activate.ps1
python -c "import asyncio; from app.gns3.client import GNS3Client; async def main():\n    async with GNS3Client() as client:\n        version = await client.get_version(); print(version.version, version.local)\nasyncio.run(main())"
```

## Current Status

Current implementation includes:

- Sprint 0 project scaffolding
- Sprint 1 topology domain model and validation
- Sprint 2 VLSM and IP addressing planner
- Sprint 3 GNS3 client and resource management layer

Business logic for GNS3 deployment, configuration application, discovery, simulation, and impact analysis is still deferred to later sprints.
