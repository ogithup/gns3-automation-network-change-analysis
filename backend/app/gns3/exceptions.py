"""Structured exceptions for GNS3 integration."""


class GNS3Error(Exception):
    """Base error for GNS3 integration."""


class GNS3ConnectionError(GNS3Error):
    """Raised when the GNS3 server cannot be reached."""


class GNS3RequestError(GNS3Error):
    """Raised when the GNS3 API returns an unexpected error."""


class GNS3ResourceNotFoundError(GNS3Error):
    """Raised when a requested project, node, or template does not exist."""


class GNS3TemplateNotFoundError(GNS3Error):
    """Raised when a logical platform cannot be resolved to a GNS3 template."""


class GNS3DeploymentError(GNS3Error):
    """Raised when deployment orchestration fails."""

