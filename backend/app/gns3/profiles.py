"""Platform profiles and interface-to-port mapping definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.gns3.exceptions import GNS3DeploymentError


class InterfacePortMapping(BaseModel):
    """Mapping from a logical interface to a GNS3 adapter/port pair."""

    adapter_number: int
    port_number: int


class PlatformProfile(BaseModel):
    """GNS3-facing platform profile for a logical device platform."""

    platform: str
    minimum_adapters: int = Field(ge=1)
    interface_map: dict[str, InterfacePortMapping]


class PlatformProfileLoader:
    """Static loader for supported Sprint 4 platform profiles."""

    def __init__(self) -> None:
        self._profiles = {
            "iosv": PlatformProfile(
                platform="iosv",
                minimum_adapters=4,
                interface_map={
                    "GigabitEthernet0/0": InterfacePortMapping(adapter_number=0, port_number=0),
                    "GigabitEthernet0/1": InterfacePortMapping(adapter_number=1, port_number=0),
                    "GigabitEthernet0/2": InterfacePortMapping(adapter_number=2, port_number=0),
                    "GigabitEthernet0/3": InterfacePortMapping(adapter_number=3, port_number=0),
                },
            ),
            "iosvl2": PlatformProfile(
                platform="iosvl2",
                minimum_adapters=8,
                interface_map={
                    "GigabitEthernet0/0": InterfacePortMapping(adapter_number=0, port_number=0),
                    "GigabitEthernet0/1": InterfacePortMapping(adapter_number=1, port_number=0),
                    "GigabitEthernet0/2": InterfacePortMapping(adapter_number=2, port_number=0),
                    "GigabitEthernet0/3": InterfacePortMapping(adapter_number=3, port_number=0),
                    "GigabitEthernet0/4": InterfacePortMapping(adapter_number=4, port_number=0),
                    "GigabitEthernet0/5": InterfacePortMapping(adapter_number=5, port_number=0),
                    "GigabitEthernet0/6": InterfacePortMapping(adapter_number=6, port_number=0),
                    "GigabitEthernet0/7": InterfacePortMapping(adapter_number=7, port_number=0),
                },
            ),
            "vpcs": PlatformProfile(
                platform="vpcs",
                minimum_adapters=1,
                interface_map={
                    "Ethernet0": InterfacePortMapping(adapter_number=0, port_number=0),
                },
            ),
        }

    def get(self, platform: str) -> PlatformProfile:
        try:
            return self._profiles[platform.lower()]
        except KeyError as error:
            raise GNS3DeploymentError(
                f"No platform profile defined for '{platform}'",
            ) from error


class PortMappingService:
    """Resolve logical interfaces to concrete GNS3 adapter/port values."""

    def __init__(self, profile_loader: PlatformProfileLoader) -> None:
        self.profile_loader = profile_loader

    def resolve(self, platform: str, interface_name: str) -> InterfacePortMapping:
        profile = self.profile_loader.get(platform)
        base_interface = interface_name.split(".")[0]
        try:
            return profile.interface_map[base_interface]
        except KeyError as error:
            raise GNS3DeploymentError(
                f"Interface '{interface_name}' is not mapped for platform '{platform}'",
            ) from error
