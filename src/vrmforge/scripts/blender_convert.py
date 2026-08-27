"""Run inside Blender: import a VRM and re-export it as VRM 1.0.

Invoked as:  blender -b --python blender_convert.py -- <src> <dst>

This is the only step in vrmforge that needs Blender, and it exists only because
no pure-Python VRM 0.x -> 1.0 converter exists yet. It resets the meta block to
restrictive defaults; the caller is responsible for restoring the true licence.
"""
import sys

import addon_utils  # type: ignore[import]
import bpy  # type: ignore[import]

argv = sys.argv[sys.argv.index("--") + 1 :]
src, dst = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
# read_factory_settings resets preferences, so the add-on must be enabled after it.
addon_utils.enable("io_scene_vrm", default_set=True, persistent=True)

bpy.ops.import_scene.vrm(filepath=src)

armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if armature is None:
    print("[vrmforge] ERROR: no armature found after import", file=sys.stderr)
    sys.exit(2)

armature.data.vrm_addon_extension.spec_version = "1.0"
bpy.ops.export_scene.vrm(filepath=dst, armature_object_name=armature.name)
print(f"[vrmforge] converted -> {dst}")
