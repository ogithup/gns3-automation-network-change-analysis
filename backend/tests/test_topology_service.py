"""Topology parsing and validation tests."""

from pathlib import Path

import pytest

from app.domain.exceptions import DomainValidationError
from app.domain.models import TopologySpec
from app.topology.service import TopologyService


def test_load_three_vlan_office_yaml() -> None:
    spec = TopologyService.load_file(
        Path(__file__).resolve().parents[2] / "examples" / "three-vlan-office.yaml",
    )

    assert spec.project.name == "three-vlan-office"
    assert len(spec.devices) == 5
    assert len(spec.vlans) == 3
    assert len(spec.links) == 4


def test_json_round_trip_preserves_project_name() -> None:
    spec = TopologyService.load_yaml(
        """
project:
  name: round-trip
devices:
  - id: r1
    hostname: R1
    type: router
    platform: iosv
    interfaces:
      - name: GigabitEthernet0/0
        ipv4_address: 10.0.0.1/30
  - id: r2
    hostname: R2
    type: router
    platform: iosv
    interfaces:
      - name: GigabitEthernet0/0
        ipv4_address: 10.0.0.2/30
links:
  - source_device: r1
    source_interface: GigabitEthernet0/0
    target_device: r2
    target_interface: GigabitEthernet0/0
""",
    )

    serialized = TopologyService.to_json(spec)
    reparsed = TopologyService.load_json(serialized)

    assert reparsed.project.name == "round-trip"
    assert reparsed.devices[0].interfaces[0].ipv4_address is not None


def test_duplicate_device_ids_raise_domain_validation_error() -> None:
    with pytest.raises(DomainValidationError, match="Duplicate device IDs"):
        TopologyService.load_yaml(
            """
project:
  name: duplicate-devices
devices:
  - id: r1
    hostname: R1
    type: router
    platform: iosv
  - id: r1
    hostname: R1B
    type: router
    platform: iosv
""",
        )


def test_missing_link_interface_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="missing interface"):
        TopologyService.load_yaml(
            """
project:
  name: bad-link
devices:
  - id: r1
    hostname: R1
    type: router
    platform: iosv
    interfaces:
      - name: GigabitEthernet0/0
  - id: sw1
    hostname: SW1
    type: switch
    platform: iosvl2
    interfaces:
      - name: GigabitEthernet0/1
links:
  - source_device: r1
    source_interface: GigabitEthernet0/9
    target_device: sw1
    target_interface: GigabitEthernet0/1
""",
        )


def test_duplicate_ip_addresses_are_rejected() -> None:
    with pytest.raises(DomainValidationError, match="Duplicate IP address"):
        TopologyService.load_yaml(
            """
project:
  name: duplicate-ip
devices:
  - id: r1
    hostname: R1
    type: router
    platform: iosv
    interfaces:
      - name: GigabitEthernet0/0
        ipv4_address: 192.168.1.1/24
endpoints:
  - id: pc1
    device_id: r1
    hostname: PC1
    ip_address: 192.168.1.1
""",
        )


def test_overlapping_subnets_are_rejected() -> None:
    with pytest.raises(DomainValidationError, match="Overlapping subnets"):
        TopologyService.load_yaml(
            """
project:
  name: overlap
subnets:
  - id: subnet-a
    name: A
    network: 10.0.0.0/24
  - id: subnet-b
    name: B
    network: 10.0.0.128/25
""",
        )


def test_gateway_outside_vlan_subnet_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside VLAN"):
        TopologyService.load_yaml(
            """
project:
  name: bad-vlan-gateway
vlans:
  - vlan_id: 10
    name: ADMIN
    subnet: 192.168.10.0/24
    gateway: 192.168.20.1
""",
        )


def test_endpoint_outside_vlan_subnet_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="outside VLAN 10 subnet"):
        TopologyService.load_yaml(
            """
project:
  name: endpoint-outside-vlan
devices:
  - id: admin-pc
    hostname: ADMIN-PC
    type: endpoint
    platform: vpcs
vlans:
  - vlan_id: 10
    name: ADMIN
    subnet: 192.168.10.0/24
    gateway: 192.168.10.1
    endpoint_ids: [admin-pc-endpoint]
endpoints:
  - id: admin-pc-endpoint
    device_id: admin-pc
    hostname: ADMIN-PC
    ip_address: 192.168.20.10
    vlan_id: 10
    default_gateway: 192.168.10.1
""",
        )


def test_invalid_acl_network_is_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid ACL selector"):
        TopologyService.load_yaml(
            """
project:
  name: invalid-acl
acls:
  - id: acl-1
    name: guest-block
    type: extended
    rules:
      - id: rule-1
        action: deny
        protocol: ip
        source: 192.168.300.0/24
        destination: any
""",
        )


def test_invalid_routing_protocol_reference_is_rejected() -> None:
    with pytest.raises(DomainValidationError, match="Routing protocol"):
        TopologyService.load_yaml(
            """
project:
  name: invalid-protocol
routing_protocols:
  - id: ospf-core
    device_id: r1
    protocol: ospf
    process_id: 1
    networks:
      - 10.0.0.0/24
""",
        )


def test_examples_are_all_loadable() -> None:
    example_dir = Path(__file__).resolve().parents[2] / "examples"

    loaded_examples: list[TopologySpec] = [
        TopologyService.load_file(path)
        for path in sorted(example_dir.glob("*.yaml"))
    ]

    assert len(loaded_examples) == 3
