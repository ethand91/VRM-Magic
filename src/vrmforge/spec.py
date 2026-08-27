"""The YAML spec schema.

Design rule, learned the hard way: every field here MUST be implemented by an
operation. `extra="forbid"` means an unknown or misspelled key is a loud
validation error. A spec that builds successfully has applied everything it
says — there is no such thing as a field that silently does nothing.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def parse_hex_color(value: str) -> tuple[float, float, float]:
    """'#1a1113' -> linear-ish RGB floats in 0..1 (sRGB values, unconverted)."""
    m = _HEX.match(value.strip())
    if not m:
        raise ValueError(f"colour must be #rrggbb, got {value!r}")
    h = m.group(1)
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetaSpec(Strict):
    """VRM 1.0 `VRMC_vrm.meta`. Every field maps to a real spec property."""

    name: str | None = None
    version: str | None = None
    authors: list[str] | None = None
    copyright_information: str | None = None
    contact_information: str | None = None
    references: list[str] | None = None
    third_party_licenses: str | None = None
    license_url: str | None = None

    avatar_permission: Literal[
        "onlyAuthor", "onlySeparatelyLicensedPerson", "everyone"
    ] | None = None
    commercial_usage: Literal[
        "personalNonProfit", "personalProfit", "corporation"
    ] | None = None
    credit_notation: Literal["required", "unnecessary"] | None = None
    modification: Literal[
        "prohibited", "allowModification", "allowModificationRedistribution"
    ] | None = None

    allow_redistribution: bool | None = None
    allow_excessively_violent_usage: bool | None = None
    allow_excessively_sexual_usage: bool | None = None
    allow_political_or_religious_usage: bool | None = None
    allow_antisocial_or_hate_usage: bool | None = None


class MaterialRule(Strict):
    """Recolour every material whose name matches `match`.

    mode='factor'  — sets baseColorFactor / MToon shadeColorFactor. Fast, but
                     these MULTIPLY the texture, so a dark texture stays dark.
    mode='texture' — rewrites the base colour image: hue and saturation are SET
                     to the target while per-pixel luminance is preserved. This
                     is a real recolour, not a blend toward the target.
    """

    match: str = Field(description="glob pattern against the material name")
    base_color: str | None = None
    shade_color: str | None = None
    emissive_color: str | None = None
    mode: Literal["factor", "texture"] = "factor"
    required: bool = Field(
        default=True,
        description="error if the pattern matches no material (catches typos)",
    )

    @field_validator("base_color", "shade_color", "emissive_color")
    @classmethod
    def _check_color(cls, v: str | None) -> str | None:
        if v is not None:
            parse_hex_color(v)
        return v


class ExpressionRule(Strict):
    """Override properties of one VRM 1.0 expression preset."""

    is_binary: bool | None = None
    override_blink: Literal["none", "block", "blend"] | None = None
    override_look_at: Literal["none", "block", "blend"] | None = None
    override_mouth: Literal["none", "block", "blend"] | None = None


class TransformSpec(Strict):
    """Scale humanoid joint nodes.

    Scaling a joint scales its whole subtree through skinning. This is a real
    transform, but it does NOT re-simulate spring bones — hair and accessory
    physics were tuned at the original scale and may need adjusting after a
    large change.
    """

    height_scale: float | None = Field(default=None, gt=0.1, lt=5.0)
    bone_scales: dict[str, float] | None = Field(
        default=None, description="VRM humanoid bone name -> uniform scale factor"
    )

    @field_validator("bone_scales")
    @classmethod
    def _check_scales(cls, v: dict[str, float] | None) -> dict[str, float] | None:
        for bone, factor in (v or {}).items():
            if not 0.1 < factor < 5.0:
                raise ValueError(f"bone_scales[{bone}]={factor} out of range (0.1, 5.0)")
        return v


class AvatarSpec(Strict):
    spec_version: Literal["1"] = "1"
    base: str = Field(description="path to the source .vrm")
    meta: MetaSpec | None = None
    materials: list[MaterialRule] = Field(default_factory=list)
    expressions: dict[str, ExpressionRule] = Field(default_factory=dict)
    transforms: TransformSpec | None = None

    @classmethod
    def load(cls, path: str | Path) -> AvatarSpec:
        raw = yaml.safe_load(Path(path).read_text())
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: spec must be a YAML mapping")
        spec = cls.model_validate(raw)
        # Resolve `base` relative to the spec file, not the cwd.
        base = Path(spec.base).expanduser()
        spec.base = str(base if base.is_absolute() else (Path(path).parent / base).resolve())
        return spec
