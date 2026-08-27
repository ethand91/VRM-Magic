# VRM-Magic

Build VRM 1.0 avatars from a YAML spec.

The Python package and CLI are named `vrmforge`.

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
git clone https://github.com/ethand91/VRM-Magic.git && cd VRM-Magic
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

Requires Python 3.10+. vrmforge edits the glTF container directly, so a build
takes milliseconds rather than the ten seconds it costs to boot a renderer.
Blender is optional and used for exactly one thing: converting a VRM 0.x base to
1.0 (see below).

## Commands

```bash
vrmforge bases                         # list built-in base avatars
vrmforge new spec.yaml -o out.vrm      # build from a base — no VRM of your own
vrmforge inspect model.vrm             # report what's actually in the file
vrmforge inspect model.vrm --json      # same, machine-readable
vrmforge check model.vrm               # validate it; non-zero exit on problems
vrmforge build spec.yaml -o out.vrm    # apply a spec to your own VRM
vrmforge build spec.yaml -o out.vrm --dry-run
```

## Starting with no VRM at all

`vrmforge new` builds from a registry base, so you need nothing but a spec:

```yaml
spec_version: "1"
base: preset:100avatars/rose      # see `vrmforge bases`

meta:
  name: Test Subject
  authors: ["you"]
transforms:
  height_scale: 0.95
```

```console
$ vrmforge new examples/from_scratch.yaml -o out/mine.vrm
  base 100avatars/rose (Rose by Polygonal Mind, CC0-1.0)
    fetched and checksum-verified -> ~/.cache/vrmforge/bases/100avatars_rose.vrm
    converting VRM 0.x -> 1.0 via Blender
    restored 11 licence field(s) from registry
  meta.name: 'undefined' -> 'Test Subject'
  transform hips: scale [1.0, 1.0, 1.0] -> [0.95, 0.95, 0.95]

wrote out/mine.vrm (2,367,816 bytes)
```

`vrmforge bases` lists 12 CC0 avatars from Polygonal Mind's 100Avatars series,
catalogued at [open-source-avatars](https://github.com/toxsam/open-source-avatars).

Bases are fetched once, **checksum-verified**, and cached under
`~/.cache/vrmforge/bases`. A base whose bytes changed is refused, not silently used.

### licenseUrl is not the content licence

VRM 1.0's `meta.licenseUrl` names the **VRM licence document**, not the licence
of the model. The actual permissions live in the structured fields
(`avatarPermission`, `commercialUsage`, `modification`, `allowRedistribution`,
`creditNotation`).

Runtimes enforce this. three-vrm's `VRMMetaLoaderPlugin` ships a whitelist
containing exactly `https://vrm.dev/licenses/1.0/` and throws on anything else:

```
VRMMetaLoaderPlugin: The license url "https://creativecommons.org/..." is not accepted
```

So vrmforge always writes the VRM licence URL and records the upstream content
licence in `copyrightInformation` — preserved, and loadable. `check` warns if it
finds a non-standard `licenseUrl`.

### Why the registry stores licence data

The only practical VRM 0.x → 1.0 converter today is Blender's VRM add-on, and it
**resets the meta block to restrictive defaults** — `onlyAuthor`,
`personalNonProfit`, `modification: prohibited`. A CC0 avatar comes out the far
side claiming to be locked down, which is not merely wrong but wrong in the
direction that matters.

So the registry records each base's true licence, and `new` restores it after
conversion, before your own `meta` is applied on top. Verify any build with
`vrmforge inspect`.

### Bases are characters, not blank mannequins

The bundled bases are complete stylised low-poly characters, not neutral bodies.
`new` is the right tool for a placeholder, a test fixture, or a starting point —
not for authoring a specific character design. For that, model in VRoid Studio
and use `vrmforge build` on the export.

Blender is needed **only** to convert a VRM 0.x base. Set `VRMFORGE_BLENDER_PATH`
if it is not on `PATH`. Working purely with VRM 1.0 files needs no Blender at all.

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

## Validating a file

`inspect` says what a file contains. `check` says whether it is *sound*:

```console
$ vrmforge check out/catgirl.vrm
catgirl.vrm: OK

$ vrmforge check broken.vrm
ERROR   [joint-out-of-range] mesh[0] 'Body' primitives[1]: joint index 68 >= 3 joints in skin[0]
WARNING [incomplete-meta] meta.licenseUrl is unset; VRM consumers display this

broken.vrm: 1 error(s), 1 warning(s)
```

It verifies buffer and accessor bounds, index and joint ranges, weight
normalisation, bind-matrix counts, node hierarchy (cycles, multiple parents),
every cross-reference between materials/textures/images/nodes/skins, the 15
required VRM humanoid bones, and spring-bone node references.

Exits non-zero on errors, so it works as a CI gate. `--strict` fails on warnings
too.

This exists because passing unit tests and being a valid *file* are different
claims. A graft can satisfy every test and still emit a joint index past the end
of a skin. Each check is covered by a test that deliberately corrupts a
known-good model and asserts the check fires — a validator that has never caught
anything only manufactures confidence.

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

**`texture` mode cannot lighten.** Preserving value is what keeps shading detail,
but it also means recolouring near-black fur to blonde leaves it near-black —
black has no hue to show. `value_scale` multiplies per-pixel brightness (clamped
at white) so dark textures can be lifted:

```yaml
- match: "*FoxTail*"
  base_color: "#d8b060"
  mode: texture
  value_scale: 2.6      # without this the fur stays black
```

## Grafting accessories between models

`parts:` transplants an accessory — cat ears, a tail, a garment — from a donor
VRM onto the base:

```yaml
parts:
  - from: models/donor.vrm
    match: "*CatEar*"        # glob against the donor's material name
```

```console
  part 'Accessory_CatEar_01_CLOTH (Instance)' from donor.vrm
    added 8 bone(s) under head
    extended skin to 69 joints, rebuilt bind matrices
    copied material with 3 texture(s)
    added primitive: 612 vertices, 914 triangles
    copied 2 spring bone chain(s)
```

**Donor and base skeletons do not have to match.** VRoid accessory bones are not
part of the core skeleton — the `J_Opt_*_CatEar*` bones parent straight to
`J_Bip_C_Head`, which is the VRM humanoid `head`. The part therefore brings its
own rig, and the base only needs a `head` bone, which every VRM has because
`head` is a required humanoid bone.

Bind matrices are **recomputed** against the target's anchor rather than copied
from the donor. A bind pose is world-space, so reusing the donor's would misplace
the part on a differently proportioned skeleton. Cat ears from a 266-bone VRoid
model land correctly on a 52-bone one.

Spring bone chains travel with the part, so the ears still wobble.

### Limits

One part per rule, and the part must be a skinned primitive with no morph
targets. Parts anchored to more than one humanoid bone are refused rather than
guessed at.

### Licensing

VRoid's built-in accessories are pixiv's assets. Grafting between models you own
is ordinary use; redistributing the result, or publishing a parts library built
from them, is not. vrmforge ships no parts — you supply the donor.

## What it does not do

**No procedural geometry.** It can move existing parts between models, but it
cannot author new ones — no restyled hair, no new garments, no body proportions
beyond scaling joint nodes.

**Joint scaling does not re-simulate spring bones.** Hair and accessory physics
were tuned at the original scale; a large change will need them retuned.

**VRM 1.0 output only.** `inspect` reads VRM 0.x correctly, and `new` can convert
a 0.x base, but `build` rejects a 0.x base with a clear message rather than
silently mangling it.

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
./.venv/bin/ruff check src tests
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
