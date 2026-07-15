"""Exceptions for approved change deployment and rollback."""


class ChangeDeploymentError(Exception):
    """Base exception for Sprint 12 change deployment workflows."""


class ChangeApprovalError(ChangeDeploymentError):
    """Raised when a change is not approved for execution."""


class UnsupportedRollbackStrategyError(ChangeDeploymentError):
    """Raised when a rollback strategy cannot be executed."""

