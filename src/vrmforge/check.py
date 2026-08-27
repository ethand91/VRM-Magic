"""Static validation of a VRM file.

The test suite proves the code is correct on synthetic fixtures. This proves a
particular FILE is sound — which is a different question, and the one that
actually bites: a graft can pass every unit test and still emit a joint index
past the end of the skin.

Every finding names the exact object at fault so it can be chased, and severity
separates "this file is broken" from "this looks wrong but may be deliberate".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vrmforge import accessors
from vrmforge.glb import Glb

# VRM 1.0 requires these humanoid bones; everything else is optional.
REQUIRED_BONES = {
    "hips", "spine", "head",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
}

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper():<7} [{self.code}] {self.message}"


def _refs_ok(findings: list[Finding], glb: Glb) -> None:
    """Every index into another array must resolve."""
    j = glb.json
    counts = {name: len(j.get(name, [])) for name in
              ("accessors", "bufferViews", "images", "textures", "materials",
               "meshes", "nodes", "skins")}

    def check(kind: str, value: Any, where: str) -> None:
        if not isinstance(value, int):
            return
        if not 0 <= value < counts.get(kind, 0):
            findings.append(
                Finding(ERROR, "dangling-ref",
                        f"{where} references {kind}[{value}] but only "
                        f"{counts.get(kind, 0)} exist")
            )

    for i, view in enumerate(j.get("bufferViews", [])):
        end = view.get("byteOffset", 0) + view["byteLength"]
        if end > len(glb.bin):
            findings.append(
                Finding(ERROR, "buffer-overrun",
                        f"bufferView[{i}] ends at {end} but the buffer is {len(glb.bin)} bytes")
            )

    for i, acc in enumerate(j.get("accessors", [])):
        if "bufferView" not in acc:
            continue
        check("bufferViews", acc["bufferView"], f"accessor[{i}]")
        in_range = acc["bufferView"] < counts["bufferViews"]
        view = j["bufferViews"][acc["bufferView"]] if in_range else None
        if view is None:
            continue
        _code, size = accessors.COMPONENT[acc["componentType"]]
        n = accessors.COMPONENT_COUNT[acc["type"]]
        stride = view.get("byteStride") or size * n
        needed = acc.get("byteOffset", 0) + (acc["count"] - 1) * stride + size * n
        if acc["count"] and needed > view["byteLength"]:
            findings.append(
                Finding(ERROR, "accessor-overrun",
                        f"accessor[{i}] needs {needed} bytes but bufferView["
                        f"{acc['bufferView']}] is {view['byteLength']}")
            )

    for i, tex in enumerate(j.get("textures", [])):
        check("images", tex.get("source"), f"texture[{i}].source")
    for i, node in enumerate(j.get("nodes", [])):
        for child in node.get("children", []):
            check("nodes", child, f"node[{i}].children")
        check("meshes", node.get("mesh"), f"node[{i}].mesh")
        check("skins", node.get("skin"), f"node[{i}].skin")
    for i, mesh in enumerate(j.get("meshes", [])):
        for pi, prim in enumerate(mesh.get("primitives", [])):
            check("materials", prim.get("material"), f"mesh[{i}].primitives[{pi}].material")
            check("accessors", prim.get("indices"), f"mesh[{i}].primitives[{pi}].indices")
            for attr, acc_index in prim.get("attributes", {}).items():
                check("accessors", acc_index, f"mesh[{i}].primitives[{pi}].{attr}")


def _hierarchy_ok(findings: list[Finding], glb: Glb) -> None:
    """A node must have at most one parent, and the tree must not cycle."""
    parent: dict[int, int] = {}
    for i, node in enumerate(glb.json.get("nodes", [])):
        for child in node.get("children", []):
            if child in parent:
                findings.append(
                    Finding(ERROR, "multiple-parents",
                            f"node[{child}] is a child of both node[{parent[child]}] "
                            f"and node[{i}]")
                )
            parent[child] = i

    for start in range(len(glb.json.get("nodes", []))):
        seen = set()
        cur: int | None = start
        while cur is not None:
            if cur in seen:
                findings.append(
                    Finding(ERROR, "node-cycle", f"node[{start}] sits in a parent cycle")
                )
                break
            seen.add(cur)
            cur = parent.get(cur)


def _skinning_ok(findings: list[Finding], glb: Glb) -> None:
    """Joint indices must be in range and weights must sum to 1."""
    j = glb.json
    skin_of_mesh: dict[int, int] = {}
    for node in j.get("nodes", []):
        if "mesh" in node and "skin" in node:
            skin_of_mesh[node["mesh"]] = node["skin"]

    for mi, mesh in enumerate(j.get("meshes", [])):
        skin_index = skin_of_mesh.get(mi)
        for pi, prim in enumerate(mesh.get("primitives", [])):
            attrs = prim.get("attributes", {})
            where = f"mesh[{mi}] '{mesh.get('name', '')}' primitives[{pi}]"

            if "indices" in prim and "POSITION" in attrs:
                vertex_count = j["accessors"][attrs["POSITION"]]["count"]
                try:
                    indices = [v[0] for v in accessors.read(glb, prim["indices"])]
                except Exception:  # noqa: BLE001 — reported by _refs_ok already
                    indices = []
                if indices and max(indices) >= vertex_count:
                    findings.append(
                        Finding(ERROR, "index-out-of-range",
                                f"{where}: index {max(indices)} >= {vertex_count} vertices")
                    )
                if len(indices) % 3:
                    findings.append(
                        Finding(WARNING, "non-triangular",
                                f"{where}: {len(indices)} indices is not a multiple of 3")
                    )

            if "JOINTS_0" not in attrs:
                continue
            if skin_index is None:
                findings.append(
                    Finding(ERROR, "unskinned-mesh",
                            f"{where} has JOINTS_0 but its node declares no skin")
                )
                continue

            joint_count = len(j["skins"][skin_index]["joints"])
            try:
                joints = accessors.read(glb, attrs["JOINTS_0"])
                weights = accessors.read(glb, attrs["WEIGHTS_0"])
            except Exception:  # noqa: BLE001
                continue

            worst = -1
            for row in joints:
                worst = max(worst, max(row))
            if worst >= joint_count:
                findings.append(
                    Finding(ERROR, "joint-out-of-range",
                            f"{where}: joint index {worst} >= {joint_count} joints in "
                            f"skin[{skin_index}]")
                )

            bad = sum(1 for row in weights if abs(sum(row) - 1.0) > 0.01)
            if bad:
                findings.append(
                    Finding(WARNING, "weights-not-normalised",
                            f"{where}: {bad}/{len(weights)} vertices have weights "
                            "not summing to 1.0")
                )

    for si, skin in enumerate(j.get("skins", [])):
        if "inverseBindMatrices" not in skin:
            continue
        declared = j["accessors"][skin["inverseBindMatrices"]]["count"]
        if declared != len(skin["joints"]):
            findings.append(
                Finding(ERROR, "bind-matrix-count",
                        f"skin[{si}] has {len(skin['joints'])} joints but "
                        f"{declared} inverse bind matrices")
            )


def _vrm_ok(findings: list[Finding], glb: Glb) -> None:
    vrm = glb.vrm
    if vrm is None:
        findings.append(
            Finding(ERROR, "not-vrm1",
                    f"no VRMC_vrm extension (detected: {glb.spec_version or 'plain glTF'})")
        )
        return

    bones = vrm.get("humanoid", {}).get("humanBones", {})
    missing = sorted(REQUIRED_BONES - set(bones))
    if missing:
        findings.append(
            Finding(ERROR, "missing-humanoid-bones",
                    f"VRM 1.0 requires these bones: {missing}")
        )

    node_count = len(glb.json.get("nodes", []))
    for bone, entry in bones.items():
        if not 0 <= entry.get("node", -1) < node_count:
            findings.append(
                Finding(ERROR, "dangling-ref",
                        f"humanoid bone {bone!r} references a node that does not exist")
            )

    meta = vrm.get("meta", {})
    from vrmforge.bases import VRM_LICENSE_URL

    url = meta.get("licenseUrl")
    if url and url != VRM_LICENSE_URL:
        findings.append(
            Finding(WARNING, "nonstandard-license-url",
                    f"meta.licenseUrl is {url!r}, not {VRM_LICENSE_URL!r}. "
                    "three-vrm rejects anything else by default "
                    "(VRMMetaLoaderPlugin: 'license url ... is not accepted'). "
                    "Put the content licence in copyrightInformation instead.")
        )

    for required in ("name", "authors", "licenseUrl"):
        if not meta.get(required):
            findings.append(
                Finding(WARNING, "incomplete-meta",
                        f"meta.{required} is unset; VRM consumers display this")
            )

    springs = glb.json.get("extensions", {}).get("VRMC_springBone", {}).get("springs", [])
    for si, spring in enumerate(springs):
        joints = spring.get("joints", [])
        if len(joints) < 2:
            findings.append(
                Finding(WARNING, "degenerate-spring",
                        f"spring[{si}] {spring.get('name', '')!r} has {len(joints)} "
                        "joint(s); a chain needs at least 2 to simulate")
            )
        for joint in joints:
            if not 0 <= joint.get("node", -1) < node_count:
                findings.append(
                    Finding(ERROR, "dangling-ref",
                            f"spring[{si}] references a node that does not exist")
                )


def validate(glb: Glb) -> list[Finding]:
    """Run every check. Errors first, then warnings."""
    findings: list[Finding] = []

    buffers = glb.json.get("buffers", [])
    if buffers and buffers[0].get("byteLength") != len(glb.bin):
        findings.append(
            Finding(ERROR, "buffer-length-mismatch",
                    f"buffers[0].byteLength is {buffers[0].get('byteLength')} but the "
                    f"binary chunk is {len(glb.bin)} bytes")
        )

    _refs_ok(findings, glb)
    _hierarchy_ok(findings, glb)
    _skinning_ok(findings, glb)
    _vrm_ok(findings, glb)

    order = {ERROR: 0, WARNING: 1}
    return sorted(findings, key=lambda f: (order[f.severity], f.code))
