"""GLB container read/write.

Deliberately dumb: the JSON chunk stays a plain dict and the BIN chunk stays
raw bytes. Nothing is parsed into typed models, so unknown extensions
(VRMC_vrm, VRMC_springBone, VRMC_materials_mtoon, vendor extras) survive a
round-trip untouched. Typed glTF libraries tend to drop what they don't know,
which silently destroys a VRM.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

_MAGIC = b"glTF"
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942


class GlbError(Exception):
    """Raised when a file is not a well-formed GLB."""


def _pad_to_4(n: int) -> int:
    return (4 - (n % 4)) % 4


@dataclass
class Glb:
    """A parsed GLB: the glTF JSON as a dict, plus the binary buffer."""

    json: dict
    bin: bytearray
    version: int = 2

    # ── Reading ──────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path) -> Glb:
        data = Path(path).read_bytes()
        if data[:4] != _MAGIC:
            raise GlbError(f"{path}: not a GLB file (magic was {data[:4]!r})")
        version, total_len = struct.unpack_from("<II", data, 4)
        if total_len > len(data):
            raise GlbError(
                f"{path}: header claims {total_len} bytes but file is {len(data)}"
            )

        gltf_json: dict | None = None
        buffer = bytearray()
        offset = 12
        while offset < total_len:
            chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
            body = data[offset + 8 : offset + 8 + chunk_len]
            if chunk_type == _CHUNK_JSON:
                gltf_json = json.loads(body.decode("utf-8"))
            elif chunk_type == _CHUNK_BIN:
                buffer = bytearray(body)
            # Unknown chunk types are skipped per the glTF spec.
            offset += 8 + chunk_len + _pad_to_4(chunk_len)

        if gltf_json is None:
            raise GlbError(f"{path}: no JSON chunk found")

        # The BIN chunk is zero-padded to a 4-byte boundary, but that padding is
        # not part of the buffer. buffers[0].byteLength is authoritative — without
        # this the length drifts by up to 3 bytes on every round-trip.
        declared = (gltf_json.get("buffers") or [{}])[0].get("byteLength")
        if isinstance(declared, int) and 0 <= declared <= len(buffer):
            buffer = buffer[:declared]

        return cls(json=gltf_json, bin=buffer, version=version)

    # ── Writing ──────────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> int:
        """Write the GLB. Returns the byte count written."""
        # buffers[0].byteLength must agree with the BIN chunk or loaders reject it.
        buffers = self.json.setdefault("buffers", [])
        if buffers:
            buffers[0]["byteLength"] = len(self.bin)
        elif self.bin:
            buffers.append({"byteLength": len(self.bin)})

        json_bytes = json.dumps(
            self.json, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        json_bytes += b" " * _pad_to_4(len(json_bytes))  # JSON pads with spaces

        bin_bytes = bytes(self.bin)
        bin_pad = b"\x00" * _pad_to_4(len(bin_bytes))  # BIN pads with zeros

        total = 12 + 8 + len(json_bytes)
        if bin_bytes:
            total += 8 + len(bin_bytes) + len(bin_pad)

        out = bytearray()
        out += _MAGIC
        out += struct.pack("<II", self.version, total)
        out += struct.pack("<II", len(json_bytes), _CHUNK_JSON)
        out += json_bytes
        if bin_bytes:
            out += struct.pack("<II", len(bin_bytes) + len(bin_pad), _CHUNK_BIN)
            out += bin_bytes
            out += bin_pad

        Path(path).write_bytes(out)
        return len(out)

    # ── Buffer growth ────────────────────────────────────────────────────────

    def append_buffer_view(self, payload: bytes) -> int:
        """Append bytes to the buffer and return the new bufferView index.

        Append-only: existing bufferView offsets stay valid, so replacing an
        image never requires rewriting every accessor in the file.
        """
        self.bin += b"\x00" * _pad_to_4(len(self.bin))  # keep 4-byte alignment
        offset = len(self.bin)
        self.bin += payload

        views = self.json.setdefault("bufferViews", [])
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(payload)})

        # Keep buffers[0].byteLength true at all times, not just at save(), so a
        # half-built Glb never looks corrupt to validation.
        buffers = self.json.setdefault("buffers", [{}])
        buffers[0]["byteLength"] = len(self.bin)

        return len(views) - 1

    # ── Convenience ──────────────────────────────────────────────────────────

    @property
    def vrm(self) -> dict | None:
        """The VRMC_vrm extension block, if this is a VRM 1.0 file."""
        return self.json.get("extensions", {}).get("VRMC_vrm")

    @property
    def vrm0(self) -> dict | None:
        """The VRM 0.x extension block, if present."""
        return self.json.get("extensions", {}).get("VRM")

    @property
    def spec_version(self) -> str | None:
        if self.vrm is not None:
            return str(self.vrm.get("specVersion", "1.0"))
        if self.vrm0 is not None:
            return "0.x"
        return None
