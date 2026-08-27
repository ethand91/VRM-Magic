"""The validator must actually catch corruption — a check that never fires is
worse than no check, because it manufactures confidence."""
from __future__ import annotations

import pytest

from vrmforge import accessors
from vrmforge.check import ERROR, validate
from vrmforge.glb import Glb
from vrmforge.graft import attach, extract


def _codes(glb, severity=ERROR):
    return {f.code for f in validate(glb) if f.severity == severity}


@pytest.fixture
def grafted(donor):
    """A structurally sound model that has had a part grafted onto it."""
    part = extract(Glb.load(donor), "*CatEar*")
    target = Glb.load(donor)
    target.json["meshes"][0]["primitives"] = []
    for node in target.json["nodes"]:
        if "CatEar" in node.get("name", ""):
            node["name"] = node["name"].replace("CatEar", "PlainBone")
    attach(target, part)
    return target


def test_a_grafted_model_has_no_errors(grafted):
    assert _codes(grafted) == set(), [str(f) for f in validate(grafted)]


def test_catches_joint_index_past_end_of_skin(grafted):
    skin = grafted.json["skins"][0]
    keep = 1
    rows = accessors.read(grafted, skin["inverseBindMatrices"])[:keep]
    skin["joints"] = skin["joints"][:keep]
    skin["inverseBindMatrices"] = accessors.write(
        grafted, rows, component_type=accessors.FLOAT, type_="MAT4"
    )
    assert "joint-out-of-range" in _codes(grafted)


def test_catches_bind_matrix_count_mismatch(grafted):
    grafted.json["skins"][0]["joints"].append(0)
    assert "bind-matrix-count" in _codes(grafted)


def test_catches_dangling_material_reference(grafted):
    grafted.json["meshes"][0]["primitives"][0]["material"] = 999
    assert "dangling-ref" in _codes(grafted)


def test_catches_buffer_length_lie(grafted):
    grafted.json["buffers"][0]["byteLength"] = 5
    assert "buffer-length-mismatch" in _codes(grafted)


def test_catches_missing_required_humanoid_bone(grafted):
    grafted.vrm["humanoid"]["humanBones"].pop("head", None)
    assert "missing-humanoid-bones" in _codes(grafted)


def test_catches_node_cycle(grafted):
    grafted.json["nodes"][0].setdefault("children", []).append(0)
    assert "node-cycle" in _codes(grafted)


def test_catches_node_with_two_parents(grafted):
    nodes = grafted.json["nodes"]
    child = nodes[0]["children"][0]
    nodes[1].setdefault("children", []).append(child)
    assert "multiple-parents" in _codes(grafted)


def test_catches_spring_referencing_missing_node(grafted):
    springs = grafted.json["extensions"]["VRMC_springBone"]["springs"]
    springs[0]["joints"][0]["node"] = 99999
    assert "dangling-ref" in _codes(grafted)


def test_catches_index_past_end_of_vertex_buffer(grafted):
    prim = grafted.json["meshes"][0]["primitives"][0]
    grafted.json["accessors"][prim["indices"]]  # exists
    prim["indices"] = accessors.write(
        grafted, [(0,), (1,), (9999,)], component_type=accessors.UINT, type_="SCALAR"
    )
    assert "index-out-of-range" in _codes(grafted)


def test_catches_accessor_overrunning_its_buffer_view(grafted):
    grafted.json["accessors"][0]["count"] = 100_000
    assert "accessor-overrun" in _codes(grafted)


def test_warns_on_unnormalised_weights(grafted):
    prim = grafted.json["meshes"][0]["primitives"][0]
    prim["attributes"]["WEIGHTS_0"] = accessors.write(
        grafted,
        [(0.5, 0.0, 0.0, 0.0)] * grafted.json["accessors"][prim["attributes"]["POSITION"]]["count"],
        component_type=accessors.FLOAT,
        type_="VEC4",
    )
    assert "weights-not-normalised" in _codes(grafted, severity="warning")


def test_non_vrm1_file_is_an_error(vrm):
    g = Glb.load(vrm)
    del g.json["extensions"]["VRMC_vrm"]
    assert "not-vrm1" in _codes(g)
