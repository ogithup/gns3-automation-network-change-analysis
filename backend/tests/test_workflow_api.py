"""Sprint 14 workflow API integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _sample_spec() -> dict:
    return {
        "project": {"name": "api-demo"},
        "devices": [
            {"id": "r1", "hostname": "R1", "type": "router", "platform": "iosv", "interfaces": [{"name": "GigabitEthernet0/0"}, {"name": "GigabitEthernet0/0.10", "ipv4_address": "192.168.10.1/24"}, {"name": "GigabitEthernet0/0.20", "ipv4_address": "192.168.20.1/24"}]},
            {"id": "sw1", "hostname": "SW1", "type": "switch", "platform": "iosvl2", "interfaces": [{"name": "GigabitEthernet0/1", "trunk_vlans": [10, 20]}, {"name": "GigabitEthernet0/2", "access_vlan": 10}, {"name": "GigabitEthernet0/3", "access_vlan": 20}]},
            {"id": "admin-pc", "hostname": "ADMIN-PC", "type": "endpoint", "platform": "vpcs", "interfaces": [{"name": "Ethernet0"}]},
            {"id": "student-pc", "hostname": "STUDENT-PC", "type": "endpoint", "platform": "vpcs", "interfaces": [{"name": "Ethernet0"}]},
        ],
        "links": [
            {"source_device": "r1", "source_interface": "GigabitEthernet0/0", "target_device": "sw1", "target_interface": "GigabitEthernet0/1"},
            {"source_device": "sw1", "source_interface": "GigabitEthernet0/2", "target_device": "admin-pc", "target_interface": "Ethernet0"},
            {"source_device": "sw1", "source_interface": "GigabitEthernet0/3", "target_device": "student-pc", "target_interface": "Ethernet0"},
        ],
        "vlans": [
            {"vlan_id": 10, "name": "ADMIN", "subnet": "192.168.10.0/24", "gateway": "192.168.10.1", "endpoint_ids": ["admin-endpoint"]},
            {"vlan_id": 20, "name": "STUDENT", "subnet": "192.168.20.0/24", "gateway": "192.168.20.1", "endpoint_ids": ["student-endpoint"]},
        ],
        "subnets": [
            {"id": "vlan10-subnet", "name": "ADMIN subnet", "network": "192.168.10.0/24", "gateway": "192.168.10.1", "vlan_id": 10},
            {"id": "vlan20-subnet", "name": "STUDENT subnet", "network": "192.168.20.0/24", "gateway": "192.168.20.1", "vlan_id": 20},
        ],
        "endpoints": [
            {"id": "admin-endpoint", "device_id": "admin-pc", "hostname": "ADMIN-PC", "ip_address": "192.168.10.10", "vlan_id": 10, "subnet_id": "vlan10-subnet", "default_gateway": "192.168.10.1"},
            {"id": "student-endpoint", "device_id": "student-pc", "hostname": "STUDENT-PC", "ip_address": "192.168.20.10", "vlan_id": 20, "subnet_id": "vlan20-subnet", "default_gateway": "192.168.20.1"},
        ],
        "connectivity_requirements": [
            {"id": "admin-to-student", "source_endpoint_id": "admin-endpoint", "target_endpoint_id": "student-endpoint", "protocol": "ping", "expected": "reachable"},
        ],
        "validation_tests": [
            {"id": "test-admin-student", "name": "Admin to Student ping", "test_type": "ping", "source_endpoint_id": "admin-endpoint", "target_endpoint_id": "student-endpoint", "expected_success": True},
        ],
    }


def test_workflow_api_end_to_end() -> None:
    client = TestClient(app)

    ai_topology_response = client.post(
        "/api/v1/ai/topology",
        json={"prompt": "Üç VLAN'lı küçük ofis ağı kur. Guest ağı Admin ağına erişemesin."},
    )
    assert ai_topology_response.status_code == 200
    assert ai_topology_response.json()["interpretation"]["topology"]["project"]["name"] == "ai-three-vlan-office"

    validate_response = client.post("/api/v1/specifications/validate", json={"specification": _sample_spec()})
    assert validate_response.status_code == 200

    deployment_response = client.post("/api/v1/deployments", json={"project_name": "api-demo", "specification": _sample_spec()})
    assert deployment_response.status_code == 200
    deployment_id = deployment_response.json()["id"]

    assert client.post(f"/api/v1/deployments/{deployment_id}/configure").status_code == 200
    assert client.post(f"/api/v1/deployments/{deployment_id}/discover").status_code == 200
    validate_runtime_response = client.post(f"/api/v1/deployments/{deployment_id}/validate")
    assert validate_runtime_response.status_code == 200
    assert validate_runtime_response.json()["status"] == "Validated"

    change_response = client.post(
        "/api/v1/changes",
        json={
            "deployment_id": deployment_id,
            "command": {"type": "REMOVE_VLAN_FROM_TRUNK", "device": "sw1", "interface": "GigabitEthernet0/1", "vlan_id": 20},
        },
    )
    assert change_response.status_code == 200
    change_id = change_response.json()["id"]

    ai_change_response = client.post(
        "/api/v1/ai/change",
        json={
            "prompt": "STUDENT VLAN'ını trunk bağlantısından kaldır.",
            "deployment_id": deployment_id,
        },
    )
    assert ai_change_response.status_code == 200
    assert ai_change_response.json()["interpretation"]["command"]["type"] == "REMOVE_VLAN_FROM_TRUNK"

    simulate_response = client.post(f"/api/v1/changes/{change_id}/simulate")
    assert simulate_response.status_code == 200
    assert simulate_response.json()["status"] == "Simulated"

    explain_response = client.post(
        "/api/v1/ai/explain",
        json={
            "simulation": simulate_response.json()["simulation"],
            "risk": simulate_response.json()["risk"],
            "validations": [],
        },
    )
    assert explain_response.status_code == 200
    assert "summary" in explain_response.json()["explanation"]

    approve_response = client.post(f"/api/v1/changes/{change_id}/approve", json={"reviewer": "tester", "approved": True})
    assert approve_response.status_code == 200

    apply_response = client.post(f"/api/v1/changes/{change_id}/apply")
    assert apply_response.status_code == 200
    assert apply_response.json()["status"] == "Completed"

    root_cause_response = client.post(
        f"/api/v1/changes/{change_id}/root-cause",
        json={"source_endpoint_id": "admin-endpoint", "target_endpoint_id": "student-endpoint"},
    )
    assert root_cause_response.status_code == 200

    report_response = client.post(
        "/api/v1/reports/generate",
        json={
            "deployment_id": deployment_id,
            "change_id": change_id,
            "user_requirements": ["Guest VLAN impact review"],
        },
    )
    assert report_response.status_code == 200
    assert "<html>" in report_response.json()["report"]["html_content"]


def test_workflow_progress_websocket_replays_history() -> None:
    client = TestClient(app)
    deployment_response = client.post("/api/v1/deployments", json={"project_name": "api-demo-ws", "specification": _sample_spec()})
    deployment_id = deployment_response.json()["id"]

    with client.websocket_connect(f"/api/v1/ws/workflows/{deployment_id}") as websocket:
        first_event = websocket.receive_json()
        assert "status" in first_event
