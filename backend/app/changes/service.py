"""Command-pattern change service for isolated topology updates."""

from __future__ import annotations

from app.changes.models import NetworkChangeCommand
from app.domain.models import TopologySpec


class ChangeService:
    """Execute typed change commands against isolated topology state."""

    @staticmethod
    def preview(command: NetworkChangeCommand, state: TopologySpec):
        updated = command.apply(state)
        diff = command.config_diff(state, updated)
        return {
            "summary": command.summary(),
            "affected_objects": command.affected_objects(),
            "diff": diff,
            "updated_state": updated,
        }

