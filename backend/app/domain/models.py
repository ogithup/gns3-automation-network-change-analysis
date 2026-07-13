"""Shared domain model placeholders for future sprints."""

from pydantic import BaseModel


class DomainPlaceholder(BaseModel):
    """Temporary placeholder model used in Sprint 0."""

    name: str = "placeholder"

