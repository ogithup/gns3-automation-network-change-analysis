"""Sprint 5 configuration generation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.configuration.exceptions import ConfigurationSyntaxError
from app.configuration.generator import ConfigurationRenderer
from app.configuration.models import RenderedConfiguration
from app.topology.service import TopologyService


def _load_topology(name: str):
    return TopologyService.load_file(Path("..") / "examples" / name)


def _snapshot_dir(name: str) -> Path:
    return Path(__file__).parent / "snapshots" / name


def test_renderer_matches_three_vlan_office_snapshots() -> None:
    topology = _load_topology("three-vlan-office.yaml")
    renderer = ConfigurationRenderer()

    preview = renderer.render_topology(topology)
    snapshot_dir = _snapshot_dir("three-vlan-office")

    assert preview.project_name == "three-vlan-office"
    for rendered in preview.rendered_configurations:
        expected_path = snapshot_dir / f"{rendered.device_id}.cfg"
        assert expected_path.read_text(encoding="utf-8") == rendered.content
        assert len(rendered.content_hash) == 64


def test_renderer_includes_ospf_for_two_router_topology() -> None:
    topology = _load_topology("two-router-ospf.yaml")
    renderer = ConfigurationRenderer()

    preview = renderer.render_topology(topology)
    r1_config = next(item for item in preview.rendered_configurations if item.device_id == "r1")

    assert "router ospf 1" in r1_config.content
    assert "network 10.0.0.0 0.0.0.3 area 0" in r1_config.content
    assert renderer.preview_text(topology).startswith("## BRANCH-A-PC (vpcs)")


def test_renderer_raises_on_invalid_syntax_output() -> None:
    invalid = RenderedConfiguration(
        device_id="pc1",
        hostname="PC1",
        platform="vpcs",
        template_name="vpcs/ip_config.j2",
        content="ip 10.0.0.2 255.255.255.0 10.0.0.1\n",
        content_hash="deadbeef",
    )

    with pytest.raises(ConfigurationSyntaxError):
        ConfigurationRenderer().syntax_validator.validate(invalid)
