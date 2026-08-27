"""vrmforge — build VRM 1.0 avatars from a YAML spec.

Every field in a spec maps to an implemented operation. Unknown fields are a
validation error and unmatched rules are a build error, so a spec that builds
has applied everything it declares.
"""
from vrmforge.glb import Glb, GlbError
from vrmforge.ops import ApplyError, build, inspect
from vrmforge.spec import AvatarSpec

__version__ = "0.1.0"
__all__ = ["Glb", "GlbError", "ApplyError", "AvatarSpec", "build", "inspect"]
