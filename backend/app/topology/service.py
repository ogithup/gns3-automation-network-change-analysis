"""Topology parsing and serialization services."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.domain.models import TopologySpec


class TopologyService:
    """Load and serialize topology documents."""

    @staticmethod
    def load_file(path: str | Path) -> TopologySpec:
        source_path = Path(path)
        suffix = source_path.suffix.lower()

        if suffix not in {".yaml", ".yml", ".json"}:
            raise ValueError(
                f"Unsupported topology file extension '{source_path.suffix}'",
            )

        raw_content = source_path.read_text(encoding="utf-8")

        if suffix in {".yaml", ".yml"}:
            return TopologyService.load_yaml(raw_content)

        return TopologyService.load_json(raw_content)

    @staticmethod
    def load_yaml(raw_content: str) -> TopologySpec:
        data = yaml.safe_load(raw_content) or {}
        return TopologySpec.model_validate(data)

    @staticmethod
    def load_json(raw_content: str) -> TopologySpec:
        data = json.loads(raw_content)
        return TopologySpec.model_validate(data)

    @staticmethod
    def to_yaml(spec: TopologySpec) -> str:
        return yaml.safe_dump(
            spec.model_dump(mode="json", exclude_none=True),
            sort_keys=False,
        )

    @staticmethod
    def to_json(spec: TopologySpec) -> str:
        return spec.model_dump_json(indent=2, exclude_none=True)

    @staticmethod
    def to_dict(spec: TopologySpec) -> dict[str, Any]:
        return spec.model_dump(mode="python", exclude_none=True)
