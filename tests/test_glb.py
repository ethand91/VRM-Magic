import json

from vrmforge.glb import Glb


def test_round_trip_is_lossless(vrm, tmp_path):
    a = Glb.load(vrm)
    out = tmp_path / "rt.vrm"
    a.save(out)
    b = Glb.load(out)
    assert a.json == b.json
    assert bytes(a.bin) == bytes(b.bin)


def test_unknown_extensions_survive(vrm, tmp_path):
    a = Glb.load(vrm)
    a.json["extensions"]["SOME_vendor_ext"] = {"payload": [1, 2, 3]}
    out = tmp_path / "ext.vrm"
    a.save(out)
    assert Glb.load(out).json["extensions"]["SOME_vendor_ext"] == {"payload": [1, 2, 3]}


def test_append_buffer_view_keeps_existing_offsets(vrm):
    g = Glb.load(vrm)
    before = json.dumps(g.json["bufferViews"][0], sort_keys=True)
    idx = g.append_buffer_view(b"hello world")
    assert json.dumps(g.json["bufferViews"][0], sort_keys=True) == before
    view = g.json["bufferViews"][idx]
    start = view["byteOffset"]
    assert bytes(g.bin[start : start + view["byteLength"]]) == b"hello world"


def test_buffer_length_tracks_bin(vrm, tmp_path):
    g = Glb.load(vrm)
    g.append_buffer_view(b"x" * 100)
    out = tmp_path / "grown.vrm"
    g.save(out)
    reloaded = Glb.load(out)
    assert reloaded.json["buffers"][0]["byteLength"] == len(reloaded.bin)


def test_spec_version_detected(vrm):
    assert Glb.load(vrm).spec_version == "1.0"


def test_repeated_round_trips_do_not_drift(vrm, tmp_path):
    """The BIN chunk's 4-byte padding must not accumulate into the buffer."""
    path = vrm
    for i in range(5):
        g = Glb.load(path)
        # Force an unaligned buffer so padding is actually exercised.
        if i == 0:
            g.append_buffer_view(b"\x01\x02\x03")
        path = tmp_path / f"gen{i}.vrm"
        g.save(path)
        reloaded = Glb.load(path)
        assert reloaded.json["buffers"][0]["byteLength"] == len(reloaded.bin)
