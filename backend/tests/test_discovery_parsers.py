"""Parser tests for Sprint 6 discovery outputs."""

from __future__ import annotations

from app.discovery.parsers import DiscoveryParserRegistry


def test_parsers_extract_interfaces_vlans_routes_and_neighbors() -> None:
    parser = DiscoveryParserRegistry()

    interface_output = """
Interface                  IP-Address      OK? Method Status                Protocol
GigabitEthernet0/0         unassigned      YES unset  administratively down down
GigabitEthernet0/1         10.0.0.1        YES manual up                    up
"""
    vlan_output = """
VLAN Name                             Status    Ports
1    default                          active    Gi0/1
10   ADMIN                            active    Gi0/2, Gi0/3
"""
    trunk_output = """
Port        Mode             Encapsulation  Status        Native vlan
Gi0/1       on               802.1q         trunking      1

Port        Vlans allowed on trunk
Gi0/1       10,20,30
"""
    route_output = """
Codes: C - connected, S - static
C    10.0.0.0/30 is directly connected, GigabitEthernet0/0
S    192.168.10.0/24 [1/0] via 10.0.0.2
"""
    acl_output = """
Extended IP access list guest-to-admin
    10 deny ip 192.168.30.0 0.0.0.255 192.168.10.0 0.0.0.255
    20 permit ip any any
"""
    ospf_output = """
Neighbor ID     Pri   State           Dead Time   Address         Interface
2.2.2.2           1   FULL/DR         00:00:32    10.0.0.2        GigabitEthernet0/0
"""

    interfaces = parser.parse_ip_interface_brief(interface_output)
    vlans = parser.parse_vlan_brief(vlan_output)
    trunks = parser.parse_interfaces_trunk(trunk_output)
    routes = parser.parse_ip_route(route_output)
    acls = parser.parse_access_lists(acl_output)
    neighbors = parser.parse_ospf_neighbors(ospf_output)

    assert interfaces[0].name == "GigabitEthernet0/0"
    assert interfaces[1].status == "up"
    assert vlans[1].vlan_id == 10
    assert vlans[1].interfaces == ["Gi0/2", "Gi0/3"]
    assert trunks[0].allowed_vlans == [10, 20, 30]
    assert routes[0].code == "C"
    assert routes[1].next_hop == "10.0.0.2"
    assert acls[0].name == "guest-to-admin"
    assert len(acls[0].entries) == 2
    assert neighbors[0].interface_name == "GigabitEthernet0/0"


def test_parsers_handle_empty_outputs() -> None:
    parser = DiscoveryParserRegistry()

    assert parser.parse_access_lists("") == []
    assert parser.parse_ospf_neighbors("") == []
    assert parser.parse_ip_route("Gateway of last resort is not set") == []
