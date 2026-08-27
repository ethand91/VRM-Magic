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
import json
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


_LICENCE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
}

# The VRM 1.0 permission block implied by each licence. This is what `new`
# restores after conversion, so it must reflect the licence accurately —
# CC-BY differs from CC0 only in requiring credit.
_LICENCE_META = {
    "CC0-1.0": {
        "avatarPermission": "everyone",
        "commercialUsage": "corporation",
        "creditNotation": "unnecessary",
        "modification": "allowModificationRedistribution",
        "allowRedistribution": True,
    },
    "CC-BY-4.0": {
        "avatarPermission": "everyone",
        "commercialUsage": "corporation",
        "creditNotation": "required",
        "modification": "allowModificationRedistribution",
        "allowRedistribution": True,
    },
}

_NEVER_ALLOWED = {
    "allowExcessivelyViolentUsage": False,
    "allowExcessivelySexualUsage": False,
    "allowPoliticalOrReligiousUsage": False,
    "allowAntisocialOrHateUsage": False,
}

_DATA_FILE = Path(__file__).parent / "bases.json"


# VRM 1.0's `licenseUrl` names the VRM LICENCE DOCUMENT, not the content licence
# — the actual permissions live in the structured fields below it. Runtimes
# enforce this: three-vrm's VRMMetaLoaderPlugin ships a whitelist containing only
# this URL and throws outright on anything else. The upstream licence is recorded
# in copyrightInformation instead, where it is preserved without breaking loaders.
VRM_LICENSE_URL = "https://vrm.dev/licenses/1.0/"


def licence_meta(licence: str, authors: list[str]) -> dict:
    """The VRM meta block implied by a licence. Raises on an unknown licence."""
    if licence not in _LICENCE_META:
        raise BaseError(
            f"no permission mapping for licence {licence!r}; "
            f"known: {sorted(_LICENCE_META)}"
        )
    credit = ", ".join(authors) if authors else "unknown"
    return {
        "licenseUrl": VRM_LICENSE_URL,
        "copyrightInformation": f"{licence} — {credit} — {_LICENCE_URLS[licence]}",
        "authors": list(authors),
        **_LICENCE_META[licence],
        **_NEVER_ALLOWED,
    }


def _load_registry() -> dict[str, Base]:
    # A missing data file means a broken install (package-data not shipped), not
    # a user error — say so rather than surfacing a bare FileNotFoundError.
    try:
        raw = json.loads(_DATA_FILE.read_text())
    except FileNotFoundError as exc:
        raise BaseError(
            f"base registry data file is missing: {_DATA_FILE}\n"
            "  This usually means the package was installed without its data files."
        ) from exc
    out: dict[str, Base] = {}
    for entry in raw["bases"]:
        licence = entry["licence"]
        out[entry["id"]] = Base(
            id=entry["id"],
            name=entry["name"],
            creator=entry["creator"],
            licence=licence,
            licence_url=_LICENCE_URLS[licence],
            source_url=entry["source_url"],
            sha256=entry["sha256"],
            spec_version=entry["spec_version"],
            size_bytes=entry["size_bytes"],
            notes=entry.get("notes", ""),
            meta=licence_meta(licence, entry.get("authors", [entry["creator"]])),
        )
    return out


REGISTRY: dict[str, Base] = _load_registry()


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
