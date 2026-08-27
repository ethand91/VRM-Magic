"""End-to-end against a real VRoid export, when one is available."""
from __future__ import annotations

from pathlib import Path

import pytest

from vrmforge.glb import Glb
from vrmforge.ops import build
from vrmforge.spec import AvatarSpec

REAL_VRM = Path.home() / "Documents" / "NekoBell.vrm"
pytestmark = pytest.mark.skipif(
    not REAL_VRM.exists(), reason="no real VRoid export on this machine"
)


def _spec(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "spec.yaml"
    p.write_text(f"spec_version: '1'\nbase: {REAL_VRM}\n{body}")
    return p


def test_build_preserves_spring_bones_and_expressions(tmp_path):
    before = Glb.load(REAL_VRM)
    spec = AvatarSpec.load(_spec(tmp_path, "meta:\n  version: '9.9'\n"))
    after, changes = build(spec)

    assert changes
    assert after.json["extensions"]["VRMC_springBone"] == before.json["extensions"]["VRMC_springBone"]
    assert (
        after.vrm["expressions"]["preset"].keys()
        == before.vrm["expressions"]["preset"].keys()
    )
    assert after.vrm["humanoid"] == before.vrm["humanoid"]


def test_texture_recolor_round_trips_through_disk(tmp_path):
    spec = AvatarSpec.load(
        _spec(
            tmp_path,
            "materials:\n  - match: '*EyeIris*'\n    base_color: '#8b2318'\n    mode: texture\n",
        )
    )
    glb, _ = build(spec)
    out = tmp_path / "out.vrm"
    glb.save(out)

    reloaded = Glb.load(out)
    assert reloaded.json["buffers"][0]["byteLength"] == len(reloaded.bin)
    assert reloaded.spec_version == "1.0"
    # Every mesh survived the buffer growth.
    assert len(reloaded.json["meshes"]) == len(glb.json["meshes"])
