"""Transplant an accessory (cat ears, a tail, a garment) between VRM models.

The insight that makes this practical: VRoid accessory bones are NOT part of the
core skeleton. Cat ears carry their own `J_Opt_*_CatEar*` bones, parented to
`J_Bip_C_Head` — which is the VRM humanoid `head` bone. The part therefore brings
its own rig with it, and the only thing the target must provide is a `head`,
which VRM guarantees because `head` is a required humanoid bone.

So a graft does not need matching skeletons. It needs a shared attachment point.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

from vrmforge import accessors
from vrmforge.glb import Glb

# Vertex attributes a graftable primitive may carry. Anything else is refused
# rather than silently dropped.
_SUPPORTED_ATTRS = {"POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"}

ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


class GraftError(Exception):
    """A part could not be extracted or attached."""


@dataclass
class BoneSpec:
    """One accessory bone, described by name so it survives the move."""

    name: str
    translation: list[float] | None
    rotation: list[float] | None
    scale: list[float] | None
    parent: str | None  # None => attaches to the humanoid anchor
    inverse_bind: tuple[float, ...] | None


@dataclass
class Part:
    """Everything needed to reproduce an accessory inside another model."""

    name: str
    attributes: dict[str, list[tuple]]
    indices: list[int]
    material: dict
    texture_payloads: dict[int, tuple[bytes, str]]  # local texture idx -> (bytes, mime)
    bones: list[BoneSpec]
    bone_order: list[str]  # JOINTS_0 values index into this
    anchor: str  # humanoid bone name the part hangs from, e.g. "head"
    springs: list[dict] = field(default_factory=list)
    # Donor node index -> bone name, so spring joint references survive the move.
    spring_node_names: dict[int, str] = field(default_factory=dict)

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3

    @property
    def vertex_count(self) -> int:
        return len(self.attributes["POSITION"])


# ── Extraction ───────────────────────────────────────────────────────────────


def _humanoid_node_names(glb: Glb) -> dict[int, str]:
    """node index -> humanoid bone name, for the VRM 1.0 humanoid block."""
    vrm = glb.vrm
    if vrm is None:
        raise GraftError("donor is not a VRM 1.0 file")
    return {
        entry["node"]: bone
        for bone, entry in vrm.get("humanoid", {}).get("humanBones", {}).items()
    }


def _parent_map(glb: Glb) -> dict[int, int]:
    out: dict[int, int] = {}
    for i, node in enumerate(glb.json["nodes"]):
        for child in node.get("children", []):
            out[child] = i
    return out


def extract(donor: Glb, pattern: str) -> Part:
    """Pull the primitive whose material matches `pattern` out of `donor`."""
    materials = donor.json.get("materials", [])
    matches = [
        (i, m)
        for i, m in enumerate(materials)
        if fnmatch.fnmatch(str(m.get("name", "")), pattern)
    ]
    if not matches:
        raise GraftError(
            f"no material matching {pattern!r} in donor.\n"
            f"  available: {[m.get('name') for m in materials]}"
        )
    if len(matches) > 1:
        raise GraftError(
            f"{pattern!r} matched {len(matches)} materials; graft handles one part "
            f"at a time.\n  matched: {[m.get('name') for _, m in matches]}"
        )
    mat_index, material = matches[0]

    found = None
    for mesh_index, mesh in enumerate(donor.json.get("meshes", [])):
        for prim in mesh.get("primitives", []):
            if prim.get("material") == mat_index:
                found = (mesh_index, prim)
                break
        if found:
            break
    if found is None:
        raise GraftError(f"material {material.get('name')!r} is not used by any primitive")
    mesh_index, prim = found

    if prim.get("targets"):
        raise GraftError(
            f"{material.get('name')!r} carries morph targets; graft does not move those yet"
        )
    unknown = set(prim["attributes"]) - _SUPPORTED_ATTRS
    if unknown:
        raise GraftError(f"{material.get('name')!r} has unsupported attributes: {sorted(unknown)}")
    for required in ("POSITION", "JOINTS_0", "WEIGHTS_0"):
        if required not in prim["attributes"]:
            raise GraftError(f"{material.get('name')!r} has no {required}; not a skinned part")

    # Primitives share one vertex pool, so compact down to the ones actually used.
    raw_indices = [v[0] for v in accessors.read(donor, prim["indices"])]
    used = sorted(set(raw_indices))
    remap = {old: new for new, old in enumerate(used)}
    indices = [remap[i] for i in raw_indices]

    attributes: dict[str, list[tuple]] = {}
    for attr, acc_index in prim["attributes"].items():
        rows = accessors.read(donor, acc_index)
        attributes[attr] = [rows[i] for i in used]

    # Resolve joints to NAMES: joint indices are file-local and meaningless elsewhere.
    node_of_mesh = next(
        (n for n in donor.json["nodes"] if n.get("mesh") == mesh_index and "skin" in n), None
    )
    if node_of_mesh is None:
        raise GraftError("the donor mesh is not skinned")
    skin = donor.json["skins"][node_of_mesh["skin"]]
    joint_nodes = skin["joints"]

    ibm = None
    if "inverseBindMatrices" in skin:
        ibm = accessors.read(donor, skin["inverseBindMatrices"])

    used_slots = set()
    for v in range(len(used)):
        for slot, weight in zip(
                attributes["JOINTS_0"][v], attributes["WEIGHTS_0"][v], strict=True
            ):
            if weight > 0:
                used_slots.add(slot)
    if not used_slots:
        raise GraftError("part has no weighted joints")

    nodes = donor.json["nodes"]
    parents = _parent_map(donor)
    humanoid = _humanoid_node_names(donor)

    # Walk up from each weighted bone, collecting the chain until we hit a
    # humanoid bone. That humanoid bone is the anchor; everything below it moves.
    bone_nodes: dict[int, None] = {}
    anchors: set[str] = set()
    for slot in used_slots:
        cur = joint_nodes[slot]
        while cur is not None and cur not in humanoid:
            bone_nodes[cur] = None
            cur = parents.get(cur)
        if cur is None:
            raise GraftError(
                f"bone {nodes[joint_nodes[slot]].get('name')!r} has no humanoid ancestor; "
                "cannot determine where this part attaches"
            )
        anchors.add(humanoid[cur])
    if len(anchors) != 1:
        raise GraftError(f"part attaches to multiple humanoid bones {sorted(anchors)}; unsupported")
    anchor = anchors.pop()

    # Pull in descendants too, so spring-bone tips travel with the part.
    stack = list(bone_nodes)
    while stack:
        cur = stack.pop()
        for child in nodes[cur].get("children", []):
            if child not in bone_nodes and child not in humanoid:
                bone_nodes[child] = None
                stack.append(child)

    slot_to_node = {slot: joint_nodes[slot] for slot in sorted(used_slots)}
    bone_order = [nodes[n].get("name", f"node{n}") for n in slot_to_node.values()]
    ibm_by_node = {joint_nodes[i]: tuple(ibm[i]) for i in range(len(joint_nodes))} if ibm else {}

    bones: list[BoneSpec] = []
    for node_index in bone_nodes:
        node = nodes[node_index]
        parent_index = parents.get(node_index)
        parent_name = (
            None
            if parent_index is None or parent_index in humanoid
            else nodes[parent_index].get("name")
        )
        bones.append(
            BoneSpec(
                name=node.get("name", f"node{node_index}"),
                translation=node.get("translation"),
                rotation=node.get("rotation"),
                scale=node.get("scale"),
                parent=parent_name,
                inverse_bind=ibm_by_node.get(node_index),
            )
        )

    # Re-express JOINTS_0 as indices into bone_order.
    slot_remap = {slot: i for i, slot in enumerate(sorted(used_slots))}
    attributes["JOINTS_0"] = [
        tuple(slot_remap.get(s, 0) for s in row) for row in attributes["JOINTS_0"]
    ]

    # Textures referenced by the material.
    payloads: dict[int, tuple[bytes, str]] = {}
    for tex_index in _material_textures(material):
        source = donor.json["textures"][tex_index].get("source")
        if source is not None:
            payloads[tex_index] = accessors.image_bytes(donor, source)

    moved_names = {b.name for b in bones}
    springs = [
        s
        for s in donor.json.get("extensions", {})
        .get("VRMC_springBone", {})
        .get("springs", [])
        if any(
            nodes[j["node"]].get("name") in moved_names for j in s.get("joints", [])
        )
    ]

    spring_node_names = {
        j["node"]: nodes[j["node"]].get("name", "")
        for s in springs
        for j in s.get("joints", [])
    }

    return Part(
        name=str(material.get("name", pattern)),
        attributes=attributes,
        indices=indices,
        material=material,
        texture_payloads=payloads,
        bones=bones,
        bone_order=bone_order,
        anchor=anchor,
        springs=springs,
        spring_node_names=spring_node_names,
    )


def _material_textures(material: dict) -> set[int]:
    found: set[int] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.endswith("Texture") and isinstance(value, dict) and "index" in value:
                    found.add(value["index"])
                else:
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(material)
    return found


# ── Attachment ───────────────────────────────────────────────────────────────


def _anchor_node(target: Glb, bone: str) -> int:
    vrm = target.vrm
    if vrm is None:
        raise GraftError("target is not a VRM 1.0 file")
    bones = vrm.get("humanoid", {}).get("humanBones", {})
    if bone not in bones:
        raise GraftError(
            f"target has no humanoid bone {bone!r}, so the part has nowhere to attach.\n"
            f"  target has: {sorted(bones)}"
        )
    return bones[bone]["node"]


def _world_matrix(glb: Glb, node_index: int) -> list[float]:
    """World transform of a node, by walking up to the root."""
    from vrmforge.matrix import IDENTITY, from_trs, multiply

    parents = _parent_map(glb)
    chain: list[int] = []
    cur: int | None = node_index
    while cur is not None:
        chain.append(cur)
        cur = parents.get(cur)

    world = list(IDENTITY)
    for idx in reversed(chain):
        node = glb.json["nodes"][idx]
        if "matrix" in node:
            raise GraftError(f"node {node.get('name')!r} uses a matrix transform; unsupported")
        world = multiply(
            world, from_trs(node.get("translation"), node.get("rotation"), node.get("scale"))
        )
    return world


def _skinned_mesh_node(target: Glb, anchor_node: int) -> tuple[int, int]:
    """Pick the skinned mesh to extend.

    Prefer a skin that already includes the anchor bone — that is the mesh the
    part belongs with. Fall back to any skinned mesh: glTF does not require the
    anchor to be a joint, and refusing would reject valid models.
    """
    candidates = [
        (i, node["skin"])
        for i, node in enumerate(target.json["nodes"])
        if "mesh" in node and "skin" in node
    ]
    if not candidates:
        raise GraftError("target has no skinned mesh to attach the part to")
    for i, skin_index in candidates:
        if anchor_node in target.json["skins"][skin_index]["joints"]:
            return i, skin_index
    return candidates[0]


def attach(target: Glb, part: Part) -> list[str]:
    """Graft `part` onto `target`. Returns a list of change descriptions."""
    from vrmforge.matrix import from_trs, invert, multiply

    changes: list[str] = []
    anchor_node = _anchor_node(target, part.anchor)
    mesh_node_index, skin_index = _skinned_mesh_node(target, anchor_node)
    mesh_index = target.json["nodes"][mesh_node_index]["mesh"]
    nodes = target.json["nodes"]

    existing = {n.get("name") for n in nodes}
    clashes = [b.name for b in part.bones if b.name in existing]
    if clashes:
        raise GraftError(
            f"target already has bone(s) {clashes}; the part appears to be attached already"
        )

    # 1. Create the bone nodes.
    new_index: dict[str, int] = {}
    for bone in part.bones:
        node: dict[str, Any] = {"name": bone.name}
        if bone.translation:
            node["translation"] = list(bone.translation)
        if bone.rotation:
            node["rotation"] = list(bone.rotation)
        if bone.scale:
            node["scale"] = list(bone.scale)
        nodes.append(node)
        new_index[bone.name] = len(nodes) - 1

    for bone in part.bones:
        child = new_index[bone.name]
        parent = new_index[bone.parent] if bone.parent else anchor_node
        nodes[parent].setdefault("children", []).append(child)
    changes.append(f"added {len(part.bones)} bone(s) under {part.anchor}")

    # 2. Recompute inverse bind matrices against the TARGET's anchor.
    #    Copying the donor's would mis-place the part on a differently
    #    proportioned skeleton — the bind pose is world-space, not local.
    anchor_world = _world_matrix(target, anchor_node)
    local_world: dict[str, list[float]] = {}
    for bone in part.bones:
        chain: list[Any] = []
        cur: BoneSpec | None = bone
        by_name = {b.name: b for b in part.bones}
        while cur is not None:
            chain.append(cur)
            cur = by_name.get(cur.parent) if cur.parent else None
        world = list(anchor_world)
        for link in reversed(chain):
            world = multiply(world, from_trs(link.translation, link.rotation, link.scale))
        local_world[bone.name] = world

    skin = target.json["skins"][skin_index]
    joint_base = len(skin["joints"])
    ibm_rows = (
        accessors.read(target, skin["inverseBindMatrices"])
        if "inverseBindMatrices" in skin
        else [tuple(invert(_world_matrix(target, n))) for n in skin["joints"]]
    )
    ibm_rows = [tuple(r) for r in ibm_rows]

    for bone_name in part.bone_order:
        skin["joints"].append(new_index[bone_name])
        ibm_rows.append(tuple(invert(local_world[bone_name])))

    skin["inverseBindMatrices"] = accessors.write(
        target, ibm_rows, component_type=accessors.FLOAT, type_="MAT4"
    )
    changes.append(f"extended skin to {len(skin['joints'])} joints, rebuilt bind matrices")

    # 3. Copy textures, then the material that points at them.
    material = _deep_copy(part.material)
    tex_remap: dict[int, int] = {}
    for old_tex, (payload, mime) in part.texture_payloads.items():
        view = target.append_buffer_view(payload)
        target.json.setdefault("images", []).append({"bufferView": view, "mimeType": mime})
        target.json.setdefault("textures", []).append({"source": len(target.json["images"]) - 1})
        tex_remap[old_tex] = len(target.json["textures"]) - 1
    _retarget_textures(material, tex_remap)
    target.json.setdefault("materials", []).append(material)
    material_index = len(target.json["materials"]) - 1
    changes.append(
        f"copied material {part.name!r} with {len(tex_remap)} texture(s)"
    )

    # 4. Vertex data. JOINTS_0 values index part.bone_order, so shift by joint_base.
    attribute_indices: dict[str, int] = {}
    for attr, rows in part.attributes.items():
        if attr == "JOINTS_0":
            rows = [tuple(v + joint_base for v in row) for row in rows]
            acc = accessors.write(
                target, rows, component_type=accessors.USHORT, type_="VEC4",
                target=ARRAY_BUFFER,
            )
        elif attr == "WEIGHTS_0":
            acc = accessors.write(
                target, rows, component_type=accessors.FLOAT, type_="VEC4",
                target=ARRAY_BUFFER,
            )
        elif attr == "TEXCOORD_0":
            acc = accessors.write(
                target, rows, component_type=accessors.FLOAT, type_="VEC2",
                target=ARRAY_BUFFER,
            )
        else:  # POSITION, NORMAL
            acc = accessors.write(
                target, rows, component_type=accessors.FLOAT, type_="VEC3",
                target=ARRAY_BUFFER,
            )
        attribute_indices[attr] = acc

    index_accessor = accessors.write(
        target,
        [(i,) for i in part.indices],
        component_type=accessors.UINT,
        type_="SCALAR",
        target=ELEMENT_ARRAY_BUFFER,
    )
    target.json["meshes"][mesh_index]["primitives"].append(
        {"attributes": attribute_indices, "indices": index_accessor, "material": material_index}
    )
    changes.append(
        f"added primitive: {part.vertex_count} vertices, {part.triangle_count} triangles"
    )

    # 5. Spring bones, with node references remapped.
    if part.springs:
        springs = (
            target.json.setdefault("extensions", {})
            .setdefault("VRMC_springBone", {"specVersion": "1.0"})
            .setdefault("springs", [])
        )
        moved = 0
        for spring in part.springs:
            joints = [
                {**j, "node": new_index[n]}
                for j in spring.get("joints", [])
                if (n := _bone_name_of(part, j["node"])) in new_index
            ]
            if len(joints) < 2:
                continue  # a chain needs at least a root and a tip to simulate
            springs.append({**{k: v for k, v in spring.items() if k != "joints"}, "joints": joints})
            moved += 1
        if moved:
            changes.append(f"copied {moved} spring bone chain(s)")

    return changes


def _bone_name_of(part: Part, donor_node_index: int) -> str | None:
    return part.spring_node_names.get(donor_node_index)


def _deep_copy(obj: Any) -> Any:
    import copy

    return copy.deepcopy(obj)


def _retarget_textures(obj: Any, remap: dict[int, int]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.endswith("Texture") and isinstance(value, dict) and "index" in value:
                if value["index"] in remap:
                    value["index"] = remap[value["index"]]
            else:
                _retarget_textures(value, remap)
    elif isinstance(obj, list):
        for item in obj:
            _retarget_textures(item, remap)
