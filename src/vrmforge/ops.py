"""Operations applied to a loaded VRM.

Each op returns a list of human-readable change descriptions. A rule that
matched nothing raises instead of returning silently — that is the whole point
of this package.
"""
from __future__ import annotations

import fnmatch
import io
from typing import Any

from vrmforge.glb import Glb
from vrmforge.spec import (
    AvatarSpec,
    ExpressionRule,
    MaterialRule,
    MetaSpec,
    TransformSpec,
    parse_hex_color,
)


class ApplyError(Exception):
    """A spec field could not be applied. Never swallowed."""


# ── Meta ─────────────────────────────────────────────────────────────────────

_META_KEYS = {
    "name": "name",
    "version": "version",
    "authors": "authors",
    "copyright_information": "copyrightInformation",
    "contact_information": "contactInformation",
    "references": "references",
    "third_party_licenses": "thirdPartyLicenses",
    "license_url": "licenseUrl",
    "avatar_permission": "avatarPermission",
    "commercial_usage": "commercialUsage",
    "credit_notation": "creditNotation",
    "modification": "modification",
    "allow_redistribution": "allowRedistribution",
    "allow_excessively_violent_usage": "allowExcessivelyViolentUsage",
    "allow_excessively_sexual_usage": "allowExcessivelySexualUsage",
    "allow_political_or_religious_usage": "allowPoliticalOrReligiousUsage",
    "allow_antisocial_or_hate_usage": "allowAntisocialOrHateUsage",
}


def apply_meta(glb: Glb, meta: MetaSpec) -> list[str]:
    vrm = glb.vrm
    if vrm is None:
        raise ApplyError("meta: not a VRM 1.0 file (no VRMC_vrm extension)")
    target = vrm.setdefault("meta", {})
    changes: list[str] = []
    for field, key in _META_KEYS.items():
        value = getattr(meta, field)
        if value is None:
            continue
        before = target.get(key)
        target[key] = value
        changes.append(f"meta.{key}: {before!r} -> {value!r}")
    return changes


# ── Materials ────────────────────────────────────────────────────────────────

_MTOON = "VRMC_materials_mtoon"


def _matching_materials(glb: Glb, pattern: str) -> list[tuple[int, dict]]:
    mats = glb.json.get("materials", [])
    return [
        (i, m)
        for i, m in enumerate(mats)
        if fnmatch.fnmatch(str(m.get("name", "")), pattern)
    ]


def _texture_use_count(glb: Glb, tex_index: int) -> int:
    """How many materials reference this texture as their base colour."""
    count = 0
    for m in glb.json.get("materials", []):
        info = m.get("pbrMetallicRoughness", {}).get("baseColorTexture")
        if info and info.get("index") == tex_index:
            count += 1
    return count


def _recolor_image_bytes(payload: bytes, rgb: tuple[float, float, float]) -> bytes:
    """Set hue and saturation to the target, preserve per-pixel value/alpha.

    This is a SET, not a blend: the output hue is the requested hue everywhere,
    while shading detail survives because V is untouched.
    """
    import colorsys

    from PIL import Image  # imported lazily so `factor` mode needs no Pillow

    img = Image.open(io.BytesIO(payload))
    img = img.convert("RGBA")
    alpha = img.getchannel("A")

    h, s, _v = colorsys.rgb_to_hsv(*rgb)
    hsv = img.convert("RGB").convert("HSV")
    _, _, v_chan = hsv.split()

    h_chan = Image.new("L", img.size, int(round(h * 255)))
    s_chan = Image.new("L", img.size, int(round(s * 255)))
    out = Image.merge("HSV", (h_chan, s_chan, v_chan)).convert("RGB")
    out.putalpha(alpha)

    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _apply_texture_recolor(
    glb: Glb, mat_index: int, mat: dict, rgb: tuple[float, float, float]
) -> str:
    info = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture")
    if not info:
        raise ApplyError(
            f"materials: '{mat.get('name')}' has no baseColorTexture; "
            "use mode: factor for this material"
        )
    tex_index = info["index"]
    textures = glb.json.setdefault("textures", [])
    images = glb.json.setdefault("images", [])

    src_index = textures[tex_index].get("source")
    if src_index is None:
        raise ApplyError(f"materials: texture {tex_index} has no image source")
    image = images[src_index]
    if "bufferView" not in image:
        raise ApplyError(
            f"materials: image {src_index} is not embedded (external URI); "
            "vrmforge only rewrites embedded images"
        )

    views = glb.json["bufferViews"]
    view = views[image["bufferView"]]
    start = view.get("byteOffset", 0)
    payload = bytes(glb.bin[start : start + view["byteLength"]])
    new_payload = _recolor_image_bytes(payload, rgb)
    new_view = glb.append_buffer_view(new_payload)

    shared = _texture_use_count(glb, tex_index) > 1
    if shared:
        # Other materials still want the original: give this one its own copy.
        images.append({"bufferView": new_view, "mimeType": "image/png"})
        textures.append({**textures[tex_index], "source": len(images) - 1})
        info["index"] = len(textures) - 1
        how = "cloned (texture was shared)"
    else:
        image["bufferView"] = new_view
        image["mimeType"] = "image/png"
        how = "rewritten in place"
    return f"  texture {how}, {len(payload)} -> {len(new_payload)} bytes"


def apply_materials(glb: Glb, rules: list[MaterialRule]) -> list[str]:
    changes: list[str] = []
    for rule in rules:
        matched = _matching_materials(glb, rule.match)
        if not matched and rule.required:
            names = [m.get("name") for m in glb.json.get("materials", [])]
            raise ApplyError(
                f"materials: pattern {rule.match!r} matched no material.\n"
                f"  available: {names}"
            )
        for idx, mat in matched:
            label = mat.get("name", f"#{idx}")
            if rule.base_color:
                rgb = parse_hex_color(rule.base_color)
                if rule.mode == "texture":
                    detail = _apply_texture_recolor(glb, idx, mat, rgb)
                    changes.append(f"material {label}: base_color -> {rule.base_color}")
                    changes.append(detail)
                else:
                    pbr = mat.setdefault("pbrMetallicRoughness", {})
                    alpha = (pbr.get("baseColorFactor") or [1, 1, 1, 1])[3]
                    pbr["baseColorFactor"] = [*rgb, alpha]
                    changes.append(
                        f"material {label}: baseColorFactor -> {rule.base_color}"
                    )
            if rule.shade_color:
                rgb = parse_hex_color(rule.shade_color)
                mtoon = mat.setdefault("extensions", {}).setdefault(_MTOON, {})
                mtoon["shadeColorFactor"] = list(rgb)
                changes.append(f"material {label}: shadeColorFactor -> {rule.shade_color}")
            if rule.emissive_color:
                rgb = parse_hex_color(rule.emissive_color)
                mat["emissiveFactor"] = list(rgb)
                changes.append(f"material {label}: emissiveFactor -> {rule.emissive_color}")
    return changes


# ── Expressions ──────────────────────────────────────────────────────────────

_EXPR_KEYS = {
    "is_binary": "isBinary",
    "override_blink": "overrideBlink",
    "override_look_at": "overrideLookAt",
    "override_mouth": "overrideMouth",
}


def apply_expressions(glb: Glb, rules: dict[str, ExpressionRule]) -> list[str]:
    vrm = glb.vrm
    if vrm is None:
        raise ApplyError("expressions: not a VRM 1.0 file")
    presets = vrm.setdefault("expressions", {}).setdefault("preset", {})
    changes: list[str] = []
    for name, rule in rules.items():
        if name not in presets:
            raise ApplyError(
                f"expressions: {name!r} is not present in this model.\n"
                f"  available: {sorted(presets)}"
            )
        target = presets[name]
        for field, key in _EXPR_KEYS.items():
            value = getattr(rule, field)
            if value is None:
                continue
            target[key] = value
            changes.append(f"expression {name}.{key} -> {value!r}")
    return changes


# ── Transforms ───────────────────────────────────────────────────────────────


def _humanoid_node(glb: Glb, bone: str) -> int:
    vrm = glb.vrm
    if vrm is None:
        raise ApplyError("transforms: not a VRM 1.0 file")
    bones = vrm.get("humanoid", {}).get("humanBones", {})
    entry = bones.get(bone)
    if entry is None:
        raise ApplyError(
            f"transforms: humanoid bone {bone!r} not found.\n"
            f"  available: {sorted(bones)}"
        )
    return entry["node"]


def _scale_node(glb: Glb, node_index: int, factor: float, label: str) -> str:
    node = glb.json["nodes"][node_index]
    if "matrix" in node:
        raise ApplyError(
            f"transforms: node for {label!r} uses a matrix transform; "
            "vrmforge only scales TRS nodes"
        )
    current = node.get("scale", [1.0, 1.0, 1.0])
    node["scale"] = [c * factor for c in current]
    return f"transform {label}: scale {current} -> {node['scale']}"


def apply_transforms(glb: Glb, transforms: TransformSpec) -> list[str]:
    changes: list[str] = []
    scales: dict[str, float] = dict(transforms.bone_scales or {})
    if transforms.height_scale is not None:
        if "hips" in scales:
            raise ApplyError(
                "transforms: set either height_scale or bone_scales.hips, not both"
            )
        scales["hips"] = transforms.height_scale
    for bone, factor in scales.items():
        changes.append(_scale_node(glb, _humanoid_node(glb, bone), factor, bone))
    return changes


# ── Orchestration ────────────────────────────────────────────────────────────


def build(spec: AvatarSpec) -> tuple[Glb, list[str]]:
    glb = Glb.load(spec.base)
    if glb.vrm is None:
        raise ApplyError(
            f"{spec.base}: not a VRM 1.0 file "
            f"(detected: {glb.spec_version or 'plain glTF'}). "
            "vrmforge v1 targets VRM 1.0 only."
        )
    changes: list[str] = []
    if spec.meta:
        changes += apply_meta(glb, spec.meta)
    if spec.materials:
        changes += apply_materials(glb, spec.materials)
    if spec.expressions:
        changes += apply_expressions(glb, spec.expressions)
    if spec.transforms:
        changes += apply_transforms(glb, spec.transforms)
    return glb, changes


def inspect(glb: Glb) -> dict[str, Any]:
    """A truthful report of what is actually in the file."""
    j = glb.json
    vrm = glb.vrm or {}
    meshes = []
    for m in j.get("meshes", []):
        prims = m.get("primitives", [])
        meshes.append(
            {
                "name": m.get("name"),
                "primitives": len(prims),
                "morph_targets": len(prims[0].get("targets", [])) if prims else 0,
            }
        )
    return {
        "spec_version": glb.spec_version,
        "meta": vrm.get("meta", {}),
        "expressions": sorted(vrm.get("expressions", {}).get("preset", {}).keys()),
        "custom_expressions": sorted(vrm.get("expressions", {}).get("custom", {}).keys()),
        "humanoid_bones": len(vrm.get("humanoid", {}).get("humanBones", {})),
        "meshes": meshes,
        "materials": [m.get("name") for m in j.get("materials", [])],
        "extensions": sorted(j.get("extensions", {}).keys()),
        "spring_bones": len(
            j.get("extensions", {}).get("VRMC_springBone", {}).get("springs", [])
        ),
    }
