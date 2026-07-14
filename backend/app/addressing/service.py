"""IPv4 addressing and VLSM planning services."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network, collapse_addresses, summarize_address_range
from math import ceil, log2

from app.addressing.models import (
    AddressingPlan,
    AddressingRequest,
    AllocationReportRow,
    HostAssignment,
    MinimalSubnetCalculation,
    PointToPointRequirement,
    SegmentAllocation,
    SegmentRequirement,
)


class AddressPlanningError(ValueError):
    """Raised when an addressing plan cannot be computed."""


class AddressingService:
    """Deterministic IPv4 addressing planner with VLSM support."""

    @staticmethod
    def plan(request: AddressingRequest) -> AddressingPlan:
        AddressingService._validate_reserved_networks(
            request.base_network,
            request.reserved_networks,
        )
        AddressingService._validate_fixed_allocations(request)

        blocked_networks = list(request.reserved_networks)
        allocations: list[SegmentAllocation] = []

        fixed_segment_requirements = [
            requirement
            for requirement in request.segments
            if requirement.fixed_subnet is not None
        ]
        floating_segment_requirements = [
            requirement
            for requirement in request.segments
            if requirement.fixed_subnet is None
        ]
        fixed_p2p_requirements = [
            requirement
            for requirement in request.point_to_point_links
            if requirement.fixed_subnet is not None
        ]
        floating_p2p_requirements = [
            requirement
            for requirement in request.point_to_point_links
            if requirement.fixed_subnet is None
        ]

        for requirement in sorted(fixed_segment_requirements, key=lambda item: item.name):
            allocation = AddressingService._allocate_fixed_segment(requirement)
            allocations.append(allocation)
            blocked_networks.append(allocation.network)

        for requirement in sorted(fixed_p2p_requirements, key=lambda item: item.name):
            allocation = AddressingService._allocate_fixed_point_to_point(requirement)
            allocations.append(allocation)
            blocked_networks.append(allocation.network)

        for requirement in sorted(
            floating_segment_requirements,
            key=lambda item: (
                -AddressingService.calculate_minimal_subnet(
                    item.required_usable_hosts,
                ).usable_hosts,
                item.name,
            ),
        ):
            candidate = AddressingService._find_next_available_subnet(
                base_network=request.base_network,
                prefix_length=AddressingService.calculate_minimal_subnet(
                    requirement.required_usable_hosts,
                ).prefix_length,
                blocked_networks=blocked_networks,
            )
            allocation = AddressingService._build_segment_allocation(
                requirement,
                candidate,
            )
            allocations.append(allocation)
            blocked_networks.append(candidate)

        for requirement in sorted(floating_p2p_requirements, key=lambda item: item.name):
            candidate = AddressingService._find_next_available_subnet(
                base_network=request.base_network,
                prefix_length=requirement.prefix_length,
                blocked_networks=blocked_networks,
            )
            allocation = AddressingService._build_point_to_point_allocation(
                requirement,
                candidate,
            )
            allocations.append(allocation)
            blocked_networks.append(candidate)

        ordered_allocations = sorted(
            allocations,
            key=lambda item: (int(item.network.network_address), item.prefix_length, item.name),
        )
        unallocated_networks = AddressingService._calculate_unallocated_networks(
            request.base_network,
            blocked_networks,
        )
        report = AddressingService._render_report(
            request.base_network,
            ordered_allocations,
            request.reserved_networks,
            unallocated_networks,
        )

        return AddressingPlan(
            base_network=request.base_network,
            allocations=ordered_allocations,
            reserved_networks=list(request.reserved_networks),
            unallocated_networks=unallocated_networks,
            report=report,
        )

    @staticmethod
    def calculate_minimal_subnet(required_usable_hosts: int) -> MinimalSubnetCalculation:
        if required_usable_hosts <= 0:
            raise AddressPlanningError("Required host count must be positive")

        host_bits = max(2, ceil(log2(required_usable_hosts + 2)))
        total_addresses = 2**host_bits
        prefix_length = 32 - host_bits
        usable_hosts = total_addresses - 2

        return MinimalSubnetCalculation(
            required_usable_hosts=required_usable_hosts,
            prefix_length=prefix_length,
            total_addresses=total_addresses,
            usable_hosts=usable_hosts,
        )

    @staticmethod
    def _build_segment_allocation(
        requirement: SegmentRequirement,
        network: IPv4Network,
    ) -> SegmentAllocation:
        calculation = AddressingService.calculate_minimal_subnet(
            requirement.required_usable_hosts,
        )
        host_assignments: list[HostAssignment] = []
        usable_hosts = list(network.hosts())

        if not usable_hosts:
            raise AddressPlanningError(
                f"Segment '{requirement.name}' network {network} has no usable host addresses",
            )

        gateway = (
            usable_hosts[0]
            if requirement.gateway_policy == "first_usable"
            else usable_hosts[-1]
        )
        host_assignments.append(
            HostAssignment(
                role="gateway",
                name=f"{requirement.name}-gateway",
                ip_address=gateway,
            ),
        )

        remaining_hosts = [host for host in usable_hosts if host != gateway]

        for index in range(requirement.switch_management_count):
            if not remaining_hosts:
                raise AddressPlanningError(
                    f"Segment '{requirement.name}' does not have enough addresses for switch management assignments",
                )
            management_ip = remaining_hosts.pop(0)
            host_assignments.append(
                HostAssignment(
                    role="switch_management",
                    name=f"{requirement.name}-switch-mgmt-{index + 1}",
                    ip_address=management_ip,
                ),
            )

        for index in range(requirement.host_count):
            if not remaining_hosts:
                raise AddressPlanningError(
                    f"Segment '{requirement.name}' does not have enough endpoint addresses",
                )
            endpoint_ip = remaining_hosts.pop(0)
            host_assignments.append(
                HostAssignment(
                    role="endpoint",
                    name=f"{requirement.name}-host-{index + 1}",
                    ip_address=endpoint_ip,
                ),
            )

        return SegmentAllocation(
            name=requirement.name,
            kind="segment",
            network=network,
            prefix_length=network.prefixlen,
            gateway=gateway,
            vlan_id=requirement.vlan_id,
            host_capacity=calculation.usable_hosts,
            requested_hosts=requirement.host_count,
            host_assignments=host_assignments,
            explanation=[
                f"Requested endpoint hosts: {requirement.host_count}",
                f"Additional switch management addresses: {requirement.switch_management_count}",
                f"Additional reserved host slots: {requirement.extra_reserved_count}",
                f"Selected minimal subnet: /{calculation.prefix_length}",
                f"Gateway policy: {requirement.gateway_policy}",
            ],
        )

    @staticmethod
    def _build_point_to_point_allocation(
        requirement: PointToPointRequirement,
        network: IPv4Network,
    ) -> SegmentAllocation:
        host_assignments: list[HostAssignment] = []
        if requirement.use_slash31:
            addresses = [network.network_address, network.broadcast_address]
        else:
            addresses = list(network.hosts())

        if len(addresses) < 2:
            raise AddressPlanningError(
                f"Point-to-point link '{requirement.name}' does not have two usable addresses",
            )

        host_assignments.append(
            HostAssignment(
                role="link_endpoint",
                name=f"{requirement.name}-a",
                ip_address=addresses[0],
            ),
        )
        host_assignments.append(
            HostAssignment(
                role="link_endpoint",
                name=f"{requirement.name}-b",
                ip_address=addresses[1],
            ),
        )

        return SegmentAllocation(
            name=requirement.name,
            kind="point_to_point",
            network=network,
            prefix_length=network.prefixlen,
            gateway=None,
            host_capacity=len(addresses),
            requested_hosts=2,
            host_assignments=host_assignments,
            explanation=[
                f"Point-to-point allocation using /{network.prefixlen}",
                "Allocated two endpoint addresses for the link",
            ],
        )

    @staticmethod
    def _allocate_fixed_segment(requirement: SegmentRequirement) -> SegmentAllocation:
        assert requirement.fixed_subnet is not None
        calculation = AddressingService.calculate_minimal_subnet(
            requirement.required_usable_hosts,
        )
        if requirement.fixed_subnet.prefixlen > calculation.prefix_length:
            raise AddressPlanningError(
                f"Fixed subnet {requirement.fixed_subnet} is too small for segment '{requirement.name}'",
            )
        return AddressingService._build_segment_allocation(
            requirement,
            requirement.fixed_subnet,
        )

    @staticmethod
    def _allocate_fixed_point_to_point(
        requirement: PointToPointRequirement,
    ) -> SegmentAllocation:
        assert requirement.fixed_subnet is not None
        if requirement.fixed_subnet.prefixlen != requirement.prefix_length:
            raise AddressPlanningError(
                f"Fixed subnet {requirement.fixed_subnet} does not match required /{requirement.prefix_length} for '{requirement.name}'",
            )
        return AddressingService._build_point_to_point_allocation(
            requirement,
            requirement.fixed_subnet,
        )

    @staticmethod
    def _validate_reserved_networks(
        base_network: IPv4Network,
        reserved_networks: list[IPv4Network],
    ) -> None:
        for network in reserved_networks:
            if not network.subnet_of(base_network):
                raise AddressPlanningError(
                    f"Reserved network {network} is outside base network {base_network}",
                )
        AddressingService._ensure_no_overlaps(reserved_networks, "reserved network")

    @staticmethod
    def _validate_fixed_allocations(request: AddressingRequest) -> None:
        fixed_networks: list[IPv4Network] = []

        for requirement in request.segments:
            if requirement.fixed_subnet is None:
                continue
            if not requirement.fixed_subnet.subnet_of(request.base_network):
                raise AddressPlanningError(
                    f"Fixed subnet {requirement.fixed_subnet} for segment '{requirement.name}' is outside base network {request.base_network}",
                )
            fixed_networks.append(requirement.fixed_subnet)

        for requirement in request.point_to_point_links:
            if requirement.fixed_subnet is None:
                continue
            if not requirement.fixed_subnet.subnet_of(request.base_network):
                raise AddressPlanningError(
                    f"Fixed subnet {requirement.fixed_subnet} for link '{requirement.name}' is outside base network {request.base_network}",
                )
            fixed_networks.append(requirement.fixed_subnet)

        AddressingService._ensure_no_overlaps(fixed_networks, "fixed network")

        for fixed_network in fixed_networks:
            for reserved_network in request.reserved_networks:
                if fixed_network.overlaps(reserved_network):
                    raise AddressPlanningError(
                        f"Fixed network {fixed_network} overlaps reserved network {reserved_network}",
                    )

    @staticmethod
    def _ensure_no_overlaps(networks: list[IPv4Network], label: str) -> None:
        sorted_networks = sorted(
            networks,
            key=lambda item: (int(item.network_address), item.prefixlen),
        )
        for index, left in enumerate(sorted_networks):
            for right in sorted_networks[index + 1 :]:
                if left.overlaps(right):
                    raise AddressPlanningError(
                        f"{label.capitalize()} overlap detected between {left} and {right}",
                    )

    @staticmethod
    def _find_next_available_subnet(
        base_network: IPv4Network,
        prefix_length: int,
        blocked_networks: list[IPv4Network],
    ) -> IPv4Network:
        if prefix_length < base_network.prefixlen:
            raise AddressPlanningError(
                f"Address space exhausted for required /{prefix_length} allocation inside {base_network}",
            )

        for candidate in base_network.subnets(new_prefix=prefix_length):
            if any(candidate.overlaps(blocked) for blocked in blocked_networks):
                continue
            return candidate

        raise AddressPlanningError(
            f"Address space exhausted for required /{prefix_length} allocation inside {base_network}",
        )

    @staticmethod
    def _calculate_unallocated_networks(
        base_network: IPv4Network,
        blocked_networks: list[IPv4Network],
    ) -> list[IPv4Network]:
        available_networks = [base_network]
        for blocked in sorted(
            blocked_networks,
            key=lambda item: (int(item.network_address), item.prefixlen),
        ):
            next_available: list[IPv4Network] = []
            for candidate in available_networks:
                if not blocked.subnet_of(candidate):
                    next_available.append(candidate)
                    continue
                next_available.extend(candidate.address_exclude(blocked))
            available_networks = next_available

        return sorted(
            available_networks,
            key=lambda item: (int(item.network_address), item.prefixlen),
        )

    @staticmethod
    def _render_report(
        base_network: IPv4Network,
        allocations: list[SegmentAllocation],
        reserved_networks: list[IPv4Network],
        unallocated_networks: list[IPv4Network],
    ) -> str:
        rows: list[AllocationReportRow] = []
        for allocation in allocations:
            rows.append(
                AllocationReportRow(
                    name=allocation.name,
                    kind=allocation.kind,
                    network=str(allocation.network),
                    gateway=str(allocation.gateway) if allocation.gateway else None,
                    notes=list(allocation.explanation),
                ),
            )

        lines = [f"Address Plan for {base_network}", ""]
        for row in rows:
            gateway_text = f" gateway={row.gateway}" if row.gateway else ""
            lines.append(f"- {row.name} [{row.kind}] -> {row.network}{gateway_text}")
            for note in row.notes:
                lines.append(f"  * {note}")

        if reserved_networks:
            lines.append("")
            lines.append("Reserved Networks:")
            for network in reserved_networks:
                lines.append(f"- {network}")

        if unallocated_networks:
            lines.append("")
            lines.append("Remaining Capacity:")
            for network in unallocated_networks:
                lines.append(f"- {network}")

        return "\n".join(lines)

    @staticmethod
    def summarize_range(start: IPv4Address, end: IPv4Address) -> list[IPv4Network]:
        """Expose deterministic range summarization for diagnostics and tests."""

        return list(summarize_address_range(start, end))

    @staticmethod
    def collapse_networks(networks: list[IPv4Network]) -> list[IPv4Network]:
        """Expose network collapsing for diagnostics and tests."""

        return list(collapse_addresses(networks))
