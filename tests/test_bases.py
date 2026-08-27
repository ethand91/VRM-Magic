"""Registry, checksum and preset-resolution behaviour. No network required."""
from __future__ import annotations

import hashlib

import pytest

from vrmforge import bases
from vrmforge.bases import Base, BaseError
from vrmforge.spec import AvatarSpec


def test_unknown_base_raises_and_lists_available():
    with pytest.raises(BaseError, match="unknown base"):
        bases.resolve("nope/missing")


def test_registry_entries_are_self_consistent():
    for base_id, base in bases.REGISTRY.items():
        assert base.id == base_id
        assert len(base.sha256) == 64, f"{base_id}: sha256 must be a full digest"
        assert base.licence, f"{base_id}: every base must record a licence"
        assert base.source_url.startswith("https://"), f"{base_id}: insecure source"
        assert base.spec_version in {"0.x", "1.0"}


def test_cc0_bases_declare_permissive_meta():
    """A CC0 base must not carry restrictive permissions into built files."""
    for base in bases.REGISTRY.values():
        if base.licence != "CC0-1.0":
            continue
        assert base.meta["avatarPermission"] == "everyone"
        assert base.meta["allowRedistribution"] is True
        assert base.meta["modification"] == "allowModificationRedistribution"


def test_fetch_rejects_wrong_checksum(tmp_path, monkeypatch):
    payload = b"not the real avatar"
    monkeypatch.setattr(bases, "cache_dir", lambda: tmp_path)

    class _FakeResponse:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(bases.urllib.request, "urlopen", lambda *a, **k: _FakeResponse())

    base = Base(
        id="test/x", name="X", creator="c", licence="CC0-1.0", licence_url="u",
        source_url="https://example.com/x.vrm", sha256="0" * 64,
        spec_version="1.0", size_bytes=len(payload),
    )
    with pytest.raises(BaseError, match="checksum mismatch"):
        bases.fetch(base)


def test_fetch_accepts_matching_checksum(tmp_path, monkeypatch):
    payload = b"pretend this is a vrm"
    monkeypatch.setattr(bases, "cache_dir", lambda: tmp_path)

    class _FakeResponse:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(bases.urllib.request, "urlopen", lambda *a, **k: _FakeResponse())

    base = Base(
        id="test/y", name="Y", creator="c", licence="CC0-1.0", licence_url="u",
        source_url="https://example.com/y.vrm",
        sha256=hashlib.sha256(payload).hexdigest(),
        spec_version="1.0", size_bytes=len(payload),
    )
    got = bases.fetch(base)
    assert got.read_bytes() == payload


def test_spec_recognises_preset_base(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("spec_version: '1'\nbase: preset:100avatars/rose\n")
    spec = AvatarSpec.load(p)
    assert spec.is_preset
    assert spec.preset_id == "100avatars/rose"
    # A preset must NOT be rewritten into a filesystem path.
    assert spec.base == "preset:100avatars/rose"


def test_spec_path_base_is_resolved_against_spec_file(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("spec_version: '1'\nbase: sub/avatar.vrm\n")
    spec = AvatarSpec.load(p)
    assert not spec.is_preset
    assert spec.base == str(tmp_path / "sub" / "avatar.vrm")
