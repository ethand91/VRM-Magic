"""Minimal 4x4 matrix maths for skinning transforms.

Column-major, matching glTF's layout. Deliberately dependency-free: pulling in
numpy for a handful of 4x4 operations is not worth the install cost.
"""
from __future__ import annotations

Mat4 = list[float]  # 16 values, column-major

IDENTITY: Mat4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def from_trs(
    translation: list[float] | None,
    rotation: list[float] | None,
    scale: list[float] | None,
) -> Mat4:
    """Compose a glTF TRS node transform. Rotation is a quaternion (x, y, z, w)."""
    tx, ty, tz = translation or (0.0, 0.0, 0.0)
    x, y, z, w = rotation or (0.0, 0.0, 0.0, 1.0)
    sx, sy, sz = scale or (1.0, 1.0, 1.0)

    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z

    return [
        (1 - 2 * (yy + zz)) * sx, (2 * (xy + wz)) * sx, (2 * (xz - wy)) * sx, 0.0,
        (2 * (xy - wz)) * sy, (1 - 2 * (xx + zz)) * sy, (2 * (yz + wx)) * sy, 0.0,
        (2 * (xz + wy)) * sz, (2 * (yz - wx)) * sz, (1 - 2 * (xx + yy)) * sz, 0.0,
        tx, ty, tz, 1.0,
    ]


def multiply(a: Mat4, b: Mat4) -> Mat4:
    """a · b, both column-major (apply b first, then a)."""
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return out


def invert(m: Mat4) -> Mat4:
    """General 4x4 inverse via Gauss-Jordan. Raises if singular."""
    # Work in row-major for readability, then transpose back.
    aug = [[m[c * 4 + r] for c in range(4)] + [1.0 if i == r else 0.0 for i in range(4)]
           for r in range(4)]

    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-12:
            raise ValueError("matrix is singular and cannot be inverted")
        aug[col], aug[pivot] = aug[pivot], aug[col]

        div = aug[col][col]
        aug[col] = [v / div for v in aug[col]]

        for row in range(4):
            if row == col:
                continue
            factor = aug[row][col]
            if factor:
                aug[row] = [v - factor * p for v, p in zip(aug[row], aug[col], strict=True)]

    return [aug[r][4 + c] for c in range(4) for r in range(4)]
