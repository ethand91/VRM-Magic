"""VRM 0.x -> 1.0 conversion, delegated to Blender's VRM add-on.

Blender is required only for this step. Everything else in vrmforge is pure
Python. If you only ever work with VRM 1.0 files, you never need Blender at all.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).parent / "scripts" / "blender_convert.py"

_MAC_DEFAULT = Path("/Applications/Blender.app/Contents/MacOS/Blender")


class ConvertError(Exception):
    """Conversion could not be performed."""


def find_blender() -> str | None:
    """Locate a Blender executable: env var, then PATH, then the macOS default."""
    explicit = os.environ.get("VRMFORGE_BLENDER_PATH", "").strip()
    if explicit:
        return explicit if Path(explicit).exists() else None
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    return str(_MAC_DEFAULT) if _MAC_DEFAULT.exists() else None


def to_vrm1(src: Path, dst: Path, *, timeout: float = 600.0) -> Path:
    """Convert a VRM 0.x file to VRM 1.0. Returns dst.

    The conversion resets the VRM meta block to restrictive defaults — callers
    must restore the true licence afterwards.
    """
    blender = find_blender()
    if blender is None:
        raise ConvertError(
            "Blender is required to convert a VRM 0.x base to 1.0, and none was found.\n"
            "  Install it (macOS: brew install --cask blender), or set "
            "VRMFORGE_BLENDER_PATH to the executable.\n"
            "  It also needs the VRM Add-on for Blender: "
            "https://github.com/saturday06/VRM-Addon-for-Blender"
        )

    dst.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [blender, "-b", "--python", str(_SCRIPT), "--", str(src), str(dst)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if not dst.exists():
        tail = (result.stderr or result.stdout or "")[-800:]
        raise ConvertError(
            f"Blender did not produce {dst}.\n"
            "  The VRM Add-on for Blender may be missing or incompatible.\n"
            f"  Blender said:\n{tail}"
        )
    return dst
