"""A minimal synthetic VRM 1.0, so tests never depend on an external file."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from vrmforge.glb import Glb


def _png(color: tuple[int, int, int], size: int = 8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), (*color, 255)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def vrm(tmp_path):
    """Write a small but structurally valid VRM 1.0 and return its path."""
    image_bytes = _png((40, 200, 60))
    bin_chunk = bytearray(image_bytes)

    gltf = {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["VRMC_vrm", "VRMC_materials_mtoon"],
        "buffers": [{"byteLength": len(bin_chunk)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(image_bytes)}
        ],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": [
            {
                "name": "Eye_Iris",
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            },
            {"name": "Hair_Back", "pbrMetallicRoughness": {}},
            {"name": "Cloth_Top", "pbrMetallicRoughness": {}},
        ],
        "meshes": [{"name": "Body", "primitives": [{"attributes": {}}]}],
        "nodes": [
            {"name": "hips", "translation": [0, 1, 0]},
            {"name": "head", "scale": [1.0, 1.0, 1.0]},
            {"name": "matrixNode", "matrix": [1] * 16},
        ],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {"name": "Fixture", "authors": ["nobody"]},
                "humanoid": {
                    "humanBones": {
                        "hips": {"node": 0},
                        "head": {"node": 1},
                        "chest": {"node": 2},
                    }
                },
                "expressions": {"preset": {"happy": {}, "blink": {}}},
            },
            "VRMC_springBone": {"springs": [{"name": "hair"}]},
        },
    }

    path = tmp_path / "fixture.vrm"
    Glb(json=gltf, bin=bin_chunk).save(path)
    return path


@pytest.fixture
def donor(tmp_path):
    """A VRM with a skinned accessory hanging off the head, like VRoid cat ears."""
    import struct

    def f32(values):
        return struct.pack(f"<{len(values)}f", *values)

    positions = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
    joints = [(0, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0)]
    weights = [(1, 0, 0, 0)] * 4
    tri = [0, 1, 2, 1, 3, 2]
    ibm = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] * 3

    blob = bytearray()
    def add(payload):
        start = len(blob)
        blob.extend(payload)
        while len(blob) % 4:
            blob.append(0)
        return start, len(payload)

    p_off, p_len = add(f32([c for v in positions for c in v]))
    j_off, j_len = add(struct.pack("<16H", *[c for v in joints for c in v]))
    w_off, w_len = add(f32([c for v in weights for c in v]))
    i_off, i_len = add(struct.pack(f"<{len(tri)}I", *tri))
    m_off, m_len = add(f32(ibm))

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": p_off, "byteLength": p_len},
            {"buffer": 0, "byteOffset": j_off, "byteLength": j_len},
            {"buffer": 0, "byteOffset": w_off, "byteLength": w_len},
            {"buffer": 0, "byteOffset": i_off, "byteLength": i_len},
            {"buffer": 0, "byteOffset": m_off, "byteLength": m_len},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 4, "type": "VEC4"},
            {"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC4"},
            {"bufferView": 3, "componentType": 5125, "count": 6, "type": "SCALAR"},
            {"bufferView": 4, "componentType": 5126, "count": 3, "type": "MAT4"},
        ],
        "materials": [{"name": "Accessory_CatEar_01"}, {"name": "Body_SKIN"}],
        "meshes": [
            {
                "name": "Body",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ],
            }
        ],
        "nodes": [
            {"name": "J_Bip_C_Head", "translation": [0, 1.5, 0],
             "children": [1, 3]},                      # 0 head (humanoid)
            {"name": "J_Opt_L_CatEar1", "translation": [-0.1, 0.1, 0], "children": [2]},
            {"name": "J_Opt_L_CatEar2", "translation": [0, 0.05, 0]},
            {"name": "J_Opt_R_CatEar1", "translation": [0.1, 0.1, 0]},
            {"name": "MeshNode", "mesh": 0, "skin": 0},
            {"name": "J_Bip_C_Hips", "translation": [0, 0.9, 0]},
        ],
        "skins": [{"joints": [1, 2, 3], "inverseBindMatrices": 4}],
        "extensions": {
            "VRMC_vrm": {
                "specVersion": "1.0",
                "meta": {"name": "Donor"},
                "humanoid": {"humanBones": {"head": {"node": 0}, "hips": {"node": 5}}},
                "expressions": {"preset": {}},
            },
            "VRMC_springBone": {
                "specVersion": "1.0",
                "springs": [
                    {"name": "CatEar", "joints": [{"node": 1}, {"node": 2}]}
                ],
            },
        },
    }
    path = tmp_path / "donor.vrm"
    Glb(json=gltf, bin=blob).save(path)
    return path
