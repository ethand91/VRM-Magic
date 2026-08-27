"""A minimal synthetic VRM 1.0, so tests never depend on an external file."""
from __future__ import annotations

import io
import struct

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
