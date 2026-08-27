"""Grafting accessories between models."""
from __future__ import annotations

import pytest

from vrmforge.glb import Glb
from vrmforge.graft import GraftError, attach, extract
from vrmforge.matrix import IDENTITY, from_trs, invert, multiply

# ── Matrix maths, since bind matrices depend on it ───────────────────────────


def test_inverse_round_trips():
    m = from_trs([1, 2, 3], [0, 0, 0, 1], [2, 2, 2])
    product = multiply(m, invert(m))
    assert all(abs(a - b) < 1e-9 for a, b in zip(product, IDENTITY, strict=True))


def test_singular_matrix_raises():
    with pytest.raises(ValueError, match="singular"):
        invert([0.0] * 16)


# ── Extraction ───────────────────────────────────────────────────────────────


def test_extract_finds_part_and_its_anchor(donor):
    part = extract(Glb.load(donor), "*CatEar*")
    assert part.anchor == "head"
    assert part.vertex_count == 4
    assert part.triangle_count == 2
    # The end bone travels with the part even though nothing is weighted to it.
    assert {b.name for b in part.bones} >= {"J_Opt_L_CatEar1", "J_Opt_L_CatEar2"}


def test_extract_rejects_unmatched_pattern(donor):
    with pytest.raises(GraftError, match="no material matching"):
        extract(Glb.load(donor), "*Wings*")


def test_extract_rejects_ambiguous_pattern(donor):
    g = Glb.load(donor)
    g.json["materials"][1]["name"] = "Accessory_CatEar_02"
    g.json["meshes"][0]["primitives"].append(
        {**g.json["meshes"][0]["primitives"][0], "material": 1}
    )
    with pytest.raises(GraftError, match="matched 2 materials"):
        extract(g, "*CatEar*")


def test_extract_refuses_morph_targets(donor):
    g = Glb.load(donor)
    g.json["meshes"][0]["primitives"][0]["targets"] = [{"POSITION": 0}]
    with pytest.raises(GraftError, match="morph targets"):
        extract(g, "*CatEar*")


def test_joints_are_reindexed_against_bone_order(donor):
    part = extract(Glb.load(donor), "*CatEar*")
    for row in part.attributes["JOINTS_0"]:
        assert all(slot < len(part.bone_order) for slot in row)



def _bare_target(donor_path):
    """A model with the accessory removed: no ear primitive, no ear bones."""
    target = Glb.load(donor_path)
    target.json["meshes"][0]["primitives"] = []
    for node in target.json["nodes"]:
        if "CatEar" in node.get("name", ""):
            node["name"] = node["name"].replace("CatEar", "PlainBone")
    return target


# ── Attachment ───────────────────────────────────────────────────────────────


def test_attach_adds_geometry_bones_and_springs(donor, tmp_path):
    part = extract(Glb.load(donor), "*CatEar*")
    target = _bare_target(donor)

    before_nodes = len(target.json["nodes"])
    changes = attach(target, part)

    assert len(target.json["nodes"]) > before_nodes
    assert target.json["meshes"][0]["primitives"], "primitive was not added"
    assert any("spring" in c for c in changes)

    # Survives a save/load cycle with a consistent buffer length.
    out = tmp_path / "grafted.vrm"
    target.save(out)
    reloaded = Glb.load(out)
    assert reloaded.json["buffers"][0]["byteLength"] == len(reloaded.bin)


def test_attach_refuses_duplicate_part(donor):
    part = extract(Glb.load(donor), "*CatEar*")
    target = Glb.load(donor)  # still has the bones
    with pytest.raises(GraftError, match="already has bone"):
        attach(target, part)


def test_attach_requires_the_anchor_bone(donor):
    part = extract(Glb.load(donor), "*CatEar*")
    target = _bare_target(donor)
    del target.vrm["humanoid"]["humanBones"]["head"]
    with pytest.raises(GraftError, match="no humanoid bone 'head'"):
        attach(target, part)


def test_bind_matrices_are_recomputed_not_copied(donor):
    """The donor's bind pose is world-space; reusing it misplaces the part."""
    from vrmforge import accessors

    part = extract(Glb.load(donor), "*CatEar*")

    target = _bare_target(donor)
    target.json["nodes"][0]["translation"] = [0, 9.0, 0]  # a much taller head

    attach(target, part)
    skin = target.json["skins"][0]
    rows = accessors.read(target, skin["inverseBindMatrices"])
    # Bind matrix translation must reflect the TARGET's head height, not the donor's.
    ty = rows[-1][13]
    assert ty < -8.0, f"bind matrix did not follow the target head: {ty}"
