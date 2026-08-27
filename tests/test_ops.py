import pytest
from pydantic import ValidationError

from vrmforge.glb import Glb
from vrmforge.ops import (
    ApplyError,
    apply_expressions,
    apply_materials,
    apply_meta,
    apply_transforms,
    inspect,
)
from vrmforge.spec import (
    AvatarSpec,
    ExpressionRule,
    MaterialRule,
    MetaSpec,
    TransformSpec,
)

# ── The core promise: nothing is ever a silent no-op ─────────────────────────


def test_unknown_spec_field_is_rejected(tmp_path):
    spec = tmp_path / "s.yaml"
    spec.write_text("spec_version: '1'\nbase: x.vrm\nhair:\n  style_id: twintails\n")
    with pytest.raises(ValidationError):
        AvatarSpec.load(spec)


def test_unmatched_material_pattern_raises(vrm):
    g = Glb.load(vrm)
    with pytest.raises(ApplyError, match="matched no material"):
        apply_materials(g, [MaterialRule(match="*Nonexistent*", base_color="#ff0000")])


def test_unmatched_pattern_allowed_when_not_required(vrm):
    g = Glb.load(vrm)
    assert apply_materials(
        g, [MaterialRule(match="*Nope*", base_color="#ff0000", required=False)]
    ) == []


def test_unknown_expression_raises(vrm):
    g = Glb.load(vrm)
    with pytest.raises(ApplyError, match="not present in this model"):
        apply_expressions(g, {"nonexistent": ExpressionRule(is_binary=True)})


def test_unknown_humanoid_bone_raises(vrm):
    g = Glb.load(vrm)
    with pytest.raises(ApplyError, match="not found"):
        apply_transforms(g, TransformSpec(bone_scales={"tail": 1.2}))


# ── Meta ─────────────────────────────────────────────────────────────────────


def test_meta_writes_vrm_camelcase_keys(vrm):
    g = Glb.load(vrm)
    apply_meta(
        g,
        MetaSpec(
            name="NekoBell",
            authors=["Ethan"],
            avatar_permission="onlyAuthor",
            allow_redistribution=False,
            credit_notation="required",
        ),
    )
    meta = g.vrm["meta"]
    assert meta["name"] == "NekoBell"
    assert meta["avatarPermission"] == "onlyAuthor"
    assert meta["allowRedistribution"] is False
    assert meta["creditNotation"] == "required"


def test_meta_leaves_unset_fields_alone(vrm):
    g = Glb.load(vrm)
    apply_meta(g, MetaSpec(name="Renamed"))
    assert g.vrm["meta"]["authors"] == ["nobody"]


# ── Materials ────────────────────────────────────────────────────────────────


def test_factor_mode_sets_base_color_factor(vrm):
    g = Glb.load(vrm)
    apply_materials(g, [MaterialRule(match="Hair_*", base_color="#ff0000")])
    factor = g.json["materials"][1]["pbrMetallicRoughness"]["baseColorFactor"]
    assert factor[:3] == pytest.approx([1.0, 0.0, 0.0])
    assert factor[3] == 1.0


def test_factor_mode_preserves_existing_alpha(vrm):
    g = Glb.load(vrm)
    g.json["materials"][1]["pbrMetallicRoughness"]["baseColorFactor"] = [1, 1, 1, 0.5]
    apply_materials(g, [MaterialRule(match="Hair_*", base_color="#00ff00")])
    assert g.json["materials"][1]["pbrMetallicRoughness"]["baseColorFactor"][3] == 0.5


def test_shade_color_writes_mtoon_extension(vrm):
    g = Glb.load(vrm)
    apply_materials(g, [MaterialRule(match="Cloth_*", shade_color="#101020")])
    mtoon = g.json["materials"][2]["extensions"]["VRMC_materials_mtoon"]
    assert mtoon["shadeColorFactor"] == pytest.approx([16 / 255, 16 / 255, 32 / 255])


def test_texture_mode_sets_hue_not_blends_it(vrm):
    """The whole point: output hue is the requested hue, not partway to it."""
    import colorsys
    import io

    from PIL import Image

    g = Glb.load(vrm)
    apply_materials(g, [MaterialRule(match="Eye_Iris", base_color="#8b2318", mode="texture")])

    image = g.json["images"][g.json["textures"][0]["source"]]
    view = g.json["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    payload = bytes(g.bin[start : start + view["byteLength"]])

    px = Image.open(io.BytesIO(payload)).convert("RGB").getpixel((4, 4))
    got_h, _, _ = colorsys.rgb_to_hsv(*[c / 255 for c in px])
    want_h, _, _ = colorsys.rgb_to_hsv(0x8B / 255, 0x23 / 255, 0x18 / 255)
    assert got_h == pytest.approx(want_h, abs=0.02)


def test_texture_mode_clones_when_texture_is_shared(vrm):
    g = Glb.load(vrm)
    # Point a second material at the same texture.
    g.json["materials"][1]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    before_images = len(g.json["images"])

    apply_materials(g, [MaterialRule(match="Eye_Iris", base_color="#0000ff", mode="texture")])

    assert len(g.json["images"]) == before_images + 1
    # The untouched material still references the original texture.
    assert g.json["materials"][1]["pbrMetallicRoughness"]["baseColorTexture"]["index"] == 0
    assert g.json["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"] != 0


def test_texture_mode_without_texture_raises(vrm):
    g = Glb.load(vrm)
    with pytest.raises(ApplyError, match="no baseColorTexture"):
        apply_materials(g, [MaterialRule(match="Hair_*", base_color="#fff000", mode="texture")])


# ── Transforms ───────────────────────────────────────────────────────────────


def test_height_scale_scales_hips_node(vrm):
    g = Glb.load(vrm)
    apply_transforms(g, TransformSpec(height_scale=0.9))
    assert g.json["nodes"][0]["scale"] == pytest.approx([0.9, 0.9, 0.9])


def test_bone_scale_multiplies_existing_scale(vrm):
    g = Glb.load(vrm)
    g.json["nodes"][1]["scale"] = [2.0, 2.0, 2.0]
    apply_transforms(g, TransformSpec(bone_scales={"head": 1.5}))
    assert g.json["nodes"][1]["scale"] == pytest.approx([3.0, 3.0, 3.0])


def test_height_scale_conflicting_with_hips_raises(vrm):
    g = Glb.load(vrm)
    with pytest.raises(ApplyError, match="not both"):
        apply_transforms(g, TransformSpec(height_scale=0.9, bone_scales={"hips": 1.1}))


def test_matrix_node_raises_rather_than_silently_skipping(vrm):
    g = Glb.load(vrm)
    with pytest.raises(ApplyError, match="matrix transform"):
        apply_transforms(g, TransformSpec(bone_scales={"chest": 1.2}))


def test_scale_out_of_range_rejected():
    with pytest.raises(ValidationError):
        TransformSpec(bone_scales={"head": 99.0})


# ── Expressions & inspect ────────────────────────────────────────────────────


def test_expression_override_written(vrm):
    g = Glb.load(vrm)
    apply_expressions(g, {"happy": ExpressionRule(is_binary=True, override_blink="block")})
    preset = g.vrm["expressions"]["preset"]["happy"]
    assert preset["isBinary"] is True
    assert preset["overrideBlink"] == "block"


def test_inspect_reports_reality(vrm):
    report = inspect(Glb.load(vrm))
    assert report["spec_version"] == "1.0"
    assert report["expressions"] == ["blink", "happy"]
    assert report["humanoid_bones"] == 3
    assert report["spring_bones"] == 1
    assert report["meshes"][0]["name"] == "Body"


def test_missing_base_file_reports_clearly_not_a_traceback(tmp_path):
    """A missing base is a user error and must read like one."""
    from vrmforge.ops import prepare_base

    spec_file = tmp_path / "s.yaml"
    spec_file.write_text("spec_version: '1'\nbase: nope.vrm\n")
    spec = AvatarSpec.load(spec_file)
    with pytest.raises(ApplyError, match="base not found"):
        prepare_base(spec)


def test_value_scale_lightens_a_dark_texture():
    """texture mode preserves brightness, so a dark texture needs a value lift
    or it stays dark whatever hue is requested."""
    import colorsys
    import io

    from PIL import Image

    from vrmforge.ops import _recolor_image_bytes

    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (20, 20, 20, 255)).save(buf, format="PNG")
    dark_png = buf.getvalue()
    blonde = (0xD8 / 255, 0xB0 / 255, 0x60 / 255)

    def mean_value(payload):
        px = list(Image.open(io.BytesIO(payload)).convert("RGB").getdata())
        return sum(colorsys.rgb_to_hsv(*[c / 255 for c in p])[2] for p in px) / len(px)

    plain = mean_value(_recolor_image_bytes(dark_png, blonde))
    lifted = mean_value(_recolor_image_bytes(dark_png, blonde, value_scale=6.0))

    # Hue is set either way, but only the lifted one is actually visible.
    assert plain < 0.15, f"value should be preserved, got {plain}"
    assert lifted > 0.4, f"value_scale did not lighten: {plain} -> {lifted}"


def test_value_scale_is_range_checked():
    with pytest.raises(ValidationError):
        MaterialRule(match="x", base_color="#ffffff", mode="texture", value_scale=0)
