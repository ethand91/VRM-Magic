# vrmforge

Build VRM 1.0 avatars from a YAML spec.

Point it at a `.vrm` you already have, describe the changes you want in YAML, and
get a new `.vrm` back — with licence metadata, material colours, expression
behaviour and joint proportions applied, and everything else preserved byte-for-byte.

```yaml
# examples/nekobell_v2.yaml — `base` is relative to the spec file
spec_version: "1"
base: ../models/avatar.vrm

meta:
  name: NekoBell
  version: "2.0"
  authors: ["Ethan"]

materials:
  - match: "*EyeIris*"
    base_color: "#8b2318"
    mode: texture
```

```console
$ vrmforge build examples/nekobell_v2.yaml -o out/nekobell_v2.vrm
base: /Users/you/vrmforge/models/avatar.vrm
  meta.name: 'NekoBell' -> 'NekoBell'
  meta.version: None -> '2.0'
  meta.authors: ['Ethan'] -> ['Ethan']
  material N00_000_00_EyeIris_00_EYE (Instance): base_color -> #8b2318
    texture rewritten in place, 124996 -> 81347 bytes

wrote out/nekobell_v2.vrm (18,099,684 bytes, 5 change(s) applied)
```

## The one design rule

**Nothing is ever a silent no-op.**

A config format that accepts a field and quietly ignores it is worse than one
that rejects it, because you can't tell the difference between "applied" and
"ignored" by looking at the output. So vrmforge refuses to be ambiguous:

- an unknown or misspelled key is a schema validation error
- a material pattern that matches nothing is a build error — and prints the
  material names that *were* available
- an expression, humanoid bone, or texture that doesn't exist is an error
- a node it cannot scale is an error, not a skip

```console
$ vrmforge build typo.yaml -o out.vrm
error: materials: pattern '*EyeIrisss*' matched no material.
  available: ['N00_000_00_FaceMouth_00_FACE (Instance)', 'N00_000_00_EyeIris_00_EYE (Instance)', ...]
```

**If `vrmforge build` exits 0, everything the spec declared was applied**, and
the change list it printed is the complete set of edits. You can trust a spec
without reading the implementation.

## Install

```bash
git clone <your-repo-url> && cd vrmforge
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

Requires Python 3.10+. No Blender, no Unity, no headless 3D app — vrmforge edits
the glTF container directly, so a build takes milliseconds rather than the ten
seconds it costs to boot a renderer.

## Commands

```bash
vrmforge inspect model.vrm             # report what's actually in the file
vrmforge inspect model.vrm --json      # same, machine-readable
vrmforge build spec.yaml -o out.vrm    # apply a spec
vrmforge build spec.yaml -o out.vrm --dry-run
```

`inspect` tells you the truth about a file — spec version, licence permissions,
expression presets, humanoid bone count, spring bones, meshes with their morph
target counts, and every material name (which is what you write globs against):

```console
$ vrmforge inspect models/avatar.vrm
avatar.vrm
  VRM spec      : 1.0
  name / authors: NekoBell / ['Ethan']
  licence       : https://vrm.dev/licenses/1.0/
  permissions   : avatar=onlyAuthor commercial=personalNonProfit mod=prohibited redistrib=False
  humanoid bones: 54
  spring bones  : 59 spring(s)
  extensions    : VRMC_springBone, VRMC_vrm
  expressions   : aa, angry, blink, blinkLeft, blinkRight, ee, happy, ih, neutral, oh, ou, relaxed, sad, surprised
  meshes:
    Face (merged)            primitives=8   morph_targets=57
    Body (merged)            primitives=14  morph_targets=0
    Hair001 (merged)         primitives=1   morph_targets=0
  materials (23):
    ...
```

## Spec reference

Every field below is implemented. There are no others — anything else is a
validation error.

```yaml
spec_version: "1"
base: ../models/avatar.vrm   # resolved relative to the spec file

meta:                        # -> VRMC_vrm.meta
  name: NekoBell
  version: "2.0"
  authors: ["Ethan"]
  copyright_information: "© 2026 Ethan"
  contact_information: "https://example.com"
  references: ["https://example.com/ref"]
  third_party_licenses: "..."
  license_url: "https://vrm.dev/licenses/1.0/"

  avatar_permission: onlyAuthor        # onlySeparatelyLicensedPerson | everyone
  commercial_usage: personalNonProfit  # personalProfit | corporation
  credit_notation: required            # unnecessary
  modification: prohibited             # allowModification | allowModificationRedistribution
  allow_redistribution: false
  allow_excessively_violent_usage: false
  allow_excessively_sexual_usage: false
  allow_political_or_religious_usage: false
  allow_antisocial_or_hate_usage: false

materials:
  - match: "*EyeIris*"       # glob against the material name
    base_color: "#8b2318"
    mode: texture            # factor (default) | texture
  - match: "*HairBack*"
    base_color: "#1a1113"
    shade_color: "#0d0809"   # MToon shadeColorFactor
    emissive_color: "#000000"
    required: false          # tolerate matching nothing (default: true)

expressions:
  happy:
    is_binary: false
    override_blink: block    # none | block | blend
    override_look_at: none
    override_mouth: none

transforms:
  height_scale: 0.95         # sugar for bone_scales.hips
  bone_scales:
    head: 1.05               # any VRM humanoid bone name
```

Unset fields are left exactly as they are in the base file. `meta` with only
`name` set will not blank out the authors.

### `factor` vs `texture` recolouring

**`factor`** sets `baseColorFactor` (and MToon `shadeColorFactor`). Fast and
lossless, but these values **multiply** the texture — a dark texture stays dark
no matter what colour you ask for. Good for tinting light or untextured surfaces.

**`texture`** rewrites the base colour image: hue and saturation are **set** to
the target while each pixel's value is preserved, so shading and detail survive.
This is a set, not a blend toward the target — ask for `#8b2318` and every pixel
comes out at that hue. Good for a decisive recolour.

Textures shared between materials are cloned before editing, so recolouring one
material never bleeds into another.

## What it does not do

**No new geometry.** It cannot add cat ears, swap an outfit, restyle hair, or
change body proportions beyond scaling joint nodes. Assembling characters from a
parts library is a separate and much larger problem.

**Joint scaling does not re-simulate spring bones.** Hair and accessory physics
were tuned at the original scale; a large change will need them retuned.

**VRM 1.0 only.** VRM 0.x files are rejected with a clear message rather than
silently mangled.

## How it works

`glb.py` is a hand-rolled GLB reader/writer, and that is deliberate. It keeps the
glTF JSON as a plain `dict` and the binary chunk as raw `bytes`, so extensions it
knows nothing about — `VRMC_vrm`, `VRMC_springBone`, `VRMC_materials_mtoon`,
vendor extras — survive a round-trip untouched. Typed glTF libraries model a
fixed schema and drop what isn't in it, which silently destroys a VRM.

Two details that matter:

- **Buffer growth is append-only.** Replacing a texture appends a new
  `bufferView` rather than rewriting the buffer, so every existing accessor
  offset stays valid.
- **The BIN chunk's 4-byte padding is not buffer content.** `load()` truncates to
  `buffers[0].byteLength`; without that, the declared length drifts by up to
  three bytes on every round-trip. Guarded by
  `test_repeated_round_trips_do_not_drift`.

## Development

```bash
./.venv/bin/python -m pytest -q
```

Tests run against a synthetic VRM built in `tests/conftest.py`, so the suite
needs no model files and no external assets. The integration tests additionally
exercise a real VRoid export if one is present, and skip cleanly if not.

## Acknowledgements

Inspired by [Seiðr-Smiðja](https://github.com/hrabanazviking/Seidr-Smidja) by
Volmarr Wyrd (Apache License 2.0), which introduced me to the idea of a
spec-driven, agent-operable VRM forge. vrmforge is an independent implementation
and shares no code with it; the "nothing is ever a silent no-op" rule is a direct
response to debugging specs whose fields quietly did nothing.

VRM is a specification by the [VRM Consortium](https://vrm.dev/). MToon is part
of the VRM specification.

## Licence

MIT — see [LICENSE](LICENSE).

Note that a `.vrm` you build with this tool carries its own licence, independent
of vrmforge's. Models exported from VRoid Studio bundle pixiv's built-in hair,
clothing and accessory assets, which have their own terms. Check what you are
allowed to do with a model before redistributing it — and keep model files out of
version control (`*.vrm` is gitignored here for exactly that reason).
