"""Domain-specific exceptions."""


class DomainError(Exception):
    """Base exception for domain logic."""


class DomainValidationError(DomainError):
    """Raised when a domain rule is violated."""


class UnsupportedChangeError(DomainError):
    """Raised when a requested change is not supported."""

