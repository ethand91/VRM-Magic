"""Typed read/write for glTF accessors.

glb.py deliberately treats the buffer as opaque bytes. Grafting geometry needs
to actually decode vertex data, so that lives here rather than polluting the
container layer.

Writes always append (see Glb.append_buffer_view), so existing accessors keep
their offsets and nothing already in the file has to be rewritten.
"""
from __future__ import annotations

import struct
from typing import Any

from vrmforge.glb import Glb

# glTF component type -> (struct code, byte size)
COMPONENT = {
    5120: ("b", 1),  # BYTE
    5121: ("B", 1),  # UNSIGNED_BYTE
    5122: ("h", 2),  # SHORT
    5123: ("H", 2),  # UNSIGNED_SHORT
    5125: ("I", 4),  # UNSIGNED_INT
    5126: ("f", 4),  # FLOAT
}

COMPONENT_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

FLOAT = 5126
USHORT = 5123
UINT = 5125


class AccessorError(Exception):
    """An accessor could not be read or written."""


def read(glb: Glb, index: int) -> list[tuple]:
    """Decode an accessor into a list of tuples (one per element)."""
    acc = glb.json["accessors"][index]
    if "bufferView" not in acc:
        # A sparse or zero-filled accessor; not something graft should guess at.
        raise AccessorError(f"accessor {index} has no bufferView (sparse accessors unsupported)")

    code, size = COMPONENT[acc["componentType"]]
    n = COMPONENT_COUNT[acc["type"]]
    view = glb.json["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    # byteStride only applies to vertex attributes; when absent, data is tight.
    stride = view.get("byteStride") or size * n
    fmt = "<" + code * n

    out: list[tuple] = []
    for i in range(acc["count"]):
        out.append(struct.unpack_from(fmt, glb.bin, start + i * stride))
    return out


def write(
    glb: Glb,
    rows: list[tuple] | list[list],
    *,
    component_type: int,
    type_: str,
    target: int | None = None,
) -> int:
    """Append data as a new accessor. Returns the accessor index."""
    code, _size = COMPONENT[component_type]
    n = COMPONENT_COUNT[type_]
    fmt = "<" + code * n

    payload = bytearray()
    for row in rows:
        if len(row) != n:
            raise AccessorError(f"expected {n} components per element, got {len(row)}")
        payload += struct.pack(fmt, *row)

    view_index = glb.append_buffer_view(bytes(payload))
    if target is not None:
        glb.json["bufferViews"][view_index]["target"] = target

    accessor: dict[str, Any] = {
        "bufferView": view_index,
        "componentType": component_type,
        "count": len(rows),
        "type": type_,
    }
    # POSITION accessors MUST carry min/max, and loaders use them for culling.
    if type_ == "VEC3" and component_type == FLOAT and rows:
        cols = list(zip(*rows, strict=True))
        accessor["min"] = [min(c) for c in cols]
        accessor["max"] = [max(c) for c in cols]

    glb.json.setdefault("accessors", []).append(accessor)
    return len(glb.json["accessors"]) - 1


def image_bytes(glb: Glb, image_index: int) -> tuple[bytes, str]:
    """Return (payload, mimeType) for an embedded image."""
    image = glb.json["images"][image_index]
    if "bufferView" not in image:
        raise AccessorError(f"image {image_index} is not embedded (external URI)")
    view = glb.json["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    return (
        bytes(glb.bin[start : start + view["byteLength"]]),
        image.get("mimeType", "image/png"),
    )
