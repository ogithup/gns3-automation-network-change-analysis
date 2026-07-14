"""Exceptions for configuration deployment and discovery."""


class DiscoveryError(Exception):
    """Base exception for discovery workflows."""


class ConsoleConnectionError(DiscoveryError):
    """Raised when a console channel cannot be established."""


class PromptDetectionError(DiscoveryError):
    """Raised when the console prompt cannot be identified."""


class ConfigurationApplyError(DiscoveryError):
    """Raised when the CLI rejects generated configuration commands."""

