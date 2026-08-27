"""The base registry — starting points for `vrmforge new`.

Every entry records its licence and creator, verified against the source rather
than assumed. Downloads are checksummed: a base whose bytes changed is refused,
not silently used.

Why licence data lives here rather than being read from the file: converting a
VRM 0.x model to 1.0 (via Blender's VRM add-on, the only practical route today)
RESETS the meta block to restrictive defaults — `onlyAuthor`, non-commercial,
modification prohibited. A CC0 avatar comes out the far side claiming to be
locked down. The registry holds the truth so `new` can restore it.
"""
from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


class BaseError(Exception):
    """A base could not be resolved, fetched, or verified."""


@dataclass(frozen=True)
class Base:
    id: str
    name: str
    creator: str
    licence: str
    licence_url: str
    source_url: str
    sha256: str
    spec_version: str
    size_bytes: int
    notes: str = ""
    # Licence permissions as they genuinely are, restored after any conversion.
    meta: dict = field(default_factory=dict)


_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"

# CC0 is asserted at collection level in the registry's projects.json; the
# per-avatar `license` field there is null. Provenance: 100Avatars by Polygonal
# Mind, catalogued at github.com/toxsam/open-source-avatars.
_CC0_META = {
    "licenseUrl": _CC0_URL,
    "avatarPermission": "everyone",
    "commercialUsage": "corporation",
    "creditNotation": "unnecessary",
    "modification": "allowModificationRedistribution",
    "allowRedistribution": True,
    "allowExcessivelyViolentUsage": False,
    "allowExcessivelySexualUsage": False,
    "allowPoliticalOrReligiousUsage": False,
    "allowAntisocialOrHateUsage": False,
}

REGISTRY: dict[str, Base] = {
    b.id: b
    for b in [
        Base(
            id="100avatars/rose",
            name="Rose",
            creator="Polygonal Mind",
            licence="CC0-1.0",
            licence_url=_CC0_URL,
            source_url="https://arweave.net/Ea1KXujzJatQgCFSMzGOzp_UtHqB1pyia--U3AtkMAY",
            sha256="8e44e5638ffdf935e5d6fa990aa6cba428269f342f2db024c2961ee286a41e5f",
            spec_version="0.x",
            size_bytes=2400964,
            notes="Stylised low-poly female humanoid. 52 humanoid bones, 16 morph targets.",
            meta={**_CC0_META, "authors": ["Polygonal Mind"]},
        ),
        Base(
            id="100avatars/robert",
            name="Robert",
            creator="Polygonal Mind",
            licence="CC0-1.0",
            licence_url=_CC0_URL,
            source_url="https://arweave.net/gwG7w4bY-A5c3R6A6GOz3xBCgbPvkFQmqPIDtvnNsYI",
            sha256="5e3edaf330577ee4c3f6440b8989af3722e7c800bb90eb037f1c05cdfe61fd7c",
            spec_version="0.x",
            size_bytes=1656464,
            notes="Stylised low-poly male humanoid.",
            meta={**_CC0_META, "authors": ["Polygonal Mind"]},
        ),
    ]
}


def cache_dir() -> Path:
    """Where fetched bases live. Honours XDG_CACHE_HOME."""
    import os

    root = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    d = Path(root) / "vrmforge" / "bases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve(base_id: str) -> Base:
    if base_id not in REGISTRY:
        raise BaseError(
            f"unknown base {base_id!r}.\n  available: {sorted(REGISTRY)}"
        )
    return REGISTRY[base_id]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(base: Base, *, force: bool = False) -> Path:
    """Download the base if needed and verify its checksum. Returns the path."""
    dest = cache_dir() / f"{base.id.replace('/', '_')}.vrm"

    if dest.exists() and not force:
        if _sha256(dest) == base.sha256:
            return dest
        dest.unlink()  # cached copy is corrupt or stale; re-fetch

    try:
        with urllib.request.urlopen(base.source_url, timeout=180) as response:
            payload = response.read()
    except Exception as exc:  # noqa: BLE001 — network errors are all equivalent here
        raise BaseError(
            f"could not download base {base.id!r} from {base.source_url}: {exc}"
        ) from exc

    got = hashlib.sha256(payload).hexdigest()
    if got != base.sha256:
        raise BaseError(
            f"checksum mismatch for base {base.id!r}.\n"
            f"  expected {base.sha256}\n  got      {got}\n"
            "  Refusing to use a base whose bytes changed."
        )

    dest.write_bytes(payload)
    return dest
