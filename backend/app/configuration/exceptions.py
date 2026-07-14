"""Configuration rendering exceptions."""


class ConfigurationError(Exception):
    """Base exception for configuration rendering failures."""


class ConfigurationSyntaxError(ConfigurationError):
    """Raised when rendered configuration fails basic validation."""


class UnsupportedPlatformError(ConfigurationError):
    """Raised when no template exists for a device platform."""

