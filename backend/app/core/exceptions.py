"""Common application exceptions."""


class NetTwinError(Exception):
    """Base exception for the NetTwin AI backend."""


class ConfigurationError(NetTwinError):
    """Raised when runtime configuration is invalid."""


class ExternalServiceError(NetTwinError):
    """Raised when an external dependency cannot be reached."""

