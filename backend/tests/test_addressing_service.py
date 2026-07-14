"""Addressing and VLSM planning tests."""

from ipaddress import IPv4Network

import pytest

from app.addressing.models import AddressingRequest, PointToPointRequirement, SegmentRequirement
from app.addressing.service import AddressPlanningError, AddressingService


def test_vlsm_allocates_largest_segments_first() -> None:
    request = AddressingRequest(
        base_network=IPv4Network("10.10.0.0/16"),
        segments=[
            SegmentRequirement(name="ADMIN", host_count=40),
            SegmentRequirement(name="STUDENT", host_count=200),
            SegmentRequirement(name="GUEST", host_count=100),
        ],
    )

    plan = AddressingService.plan(request)
    segment_networks = {allocation.name: allocation.network for allocation in plan.allocations}

    assert segment_networks["STUDENT"] == IPv4Network("10.10.0.0/24")
    assert segment_networks["GUEST"] == IPv4Network("10.10.1.0/25")
    assert segment_networks["ADMIN"] == IPv4Network("10.10.1.128/26")


def test_gateway_and_host_assignments_are_generated() -> None:
    plan = AddressingService.plan(
        AddressingRequest(
            base_network=IPv4Network("192.168.0.0/24"),
            segments=[
                SegmentRequirement(
                    name="ADMIN",
                    host_count=3,
                    switch_management_count=1,
                ),
            ],
        ),
    )

    allocation = plan.allocations[0]
    assignment_roles = [assignment.role for assignment in allocation.host_assignments]

    assert str(allocation.gateway) == "192.168.0.1"
    assert assignment_roles == [
        "gateway",
        "switch_management",
        "endpoint",
        "endpoint",
        "endpoint",
    ]


def test_reserved_networks_are_skipped() -> None:
    plan = AddressingService.plan(
        AddressingRequest(
            base_network=IPv4Network("10.0.0.0/24"),
            reserved_networks=[IPv4Network("10.0.0.0/26")],
            segments=[SegmentRequirement(name="USERS", host_count=30)],
        ),
    )

    assert plan.allocations[0].network == IPv4Network("10.0.0.64/26")


def test_fixed_subnet_is_respected() -> None:
    plan = AddressingService.plan(
        AddressingRequest(
            base_network=IPv4Network("10.20.0.0/24"),
            segments=[
                SegmentRequirement(
                    name="VOICE",
                    host_count=20,
                    fixed_subnet=IPv4Network("10.20.0.128/27"),
                ),
            ],
        ),
    )

    assert plan.allocations[0].network == IPv4Network("10.20.0.128/27")


def test_fixed_subnet_too_small_is_rejected() -> None:
    with pytest.raises(AddressPlanningError, match="too small"):
        AddressingService.plan(
            AddressingRequest(
                base_network=IPv4Network("10.20.0.0/24"),
                segments=[
                    SegmentRequirement(
                        name="VOICE",
                        host_count=40,
                        fixed_subnet=IPv4Network("10.20.0.128/27"),
                    ),
                ],
            ),
        )


def test_address_exhaustion_is_detected() -> None:
    with pytest.raises(AddressPlanningError, match="Address space exhausted"):
        AddressingService.plan(
            AddressingRequest(
                base_network=IPv4Network("192.168.1.0/29"),
                segments=[SegmentRequirement(name="LAB", host_count=10)],
            ),
        )


def test_overlapping_reserved_networks_are_rejected() -> None:
    with pytest.raises(AddressPlanningError, match="overlap detected"):
        AddressingService.plan(
            AddressingRequest(
                base_network=IPv4Network("10.0.0.0/24"),
                reserved_networks=[
                    IPv4Network("10.0.0.0/26"),
                    IPv4Network("10.0.0.32/27"),
                ],
            ),
        )


def test_point_to_point_slash30_and_slash31_are_supported() -> None:
    plan = AddressingService.plan(
        AddressingRequest(
            base_network=IPv4Network("172.16.0.0/24"),
            point_to_point_links=[
                PointToPointRequirement(name="wan-a"),
                PointToPointRequirement(name="wan-b", use_slash31=True),
            ],
        ),
    )

    allocation_map = {allocation.name: allocation for allocation in plan.allocations}

    assert allocation_map["wan-a"].network.prefixlen == 30
    assert allocation_map["wan-b"].network.prefixlen == 31
    assert len(allocation_map["wan-a"].host_assignments) == 2
    assert len(allocation_map["wan-b"].host_assignments) == 2


def test_report_contains_explainable_output() -> None:
    plan = AddressingService.plan(
        AddressingRequest(
            base_network=IPv4Network("10.30.0.0/24"),
            segments=[SegmentRequirement(name="GUEST", host_count=20)],
        ),
    )

    assert "Address Plan for 10.30.0.0/24" in plan.report
    assert "GUEST [segment]" in plan.report
    assert "Gateway policy: first_usable" in plan.report

