import json

import pytest

from ntrack.rng import Random, Uheprng
from ntrack import config
from ntrack.track import generate_track
from ntrack.userscript import (
    ANIMATOR_BUNDLE,
    build_2d_preview_html,
    build_preview_html,
    build_userscript,
)


def test_uheprng_deterministic():
    seq_a = [Uheprng("seed").random() for _ in range(50)]
    seq_b = [Uheprng("seed").random() for _ in range(50)]
    assert seq_a == seq_b


def test_uheprng_range():
    rng = Uheprng("abc")
    for _ in range(1000):
        v = rng.random()
        assert 0.0 <= v < 1.0


def test_uheprng_different_seeds_differ():
    seq_a = [Uheprng("one").random() for _ in range(20)]
    seq_b = [Uheprng("two").random() for _ in range(20)]
    assert seq_a != seq_b


def test_int_between_inclusive_bounds():
    rng = Uheprng("bounds")
    for _ in range(500):
        v = rng.int_between(2, 5)
        assert 2 <= v <= 5
        assert isinstance(v, int)


def test_float_between_range():
    rng = Uheprng("floats")
    for _ in range(500):
        v = rng.float_between(-1.0, 1.0)
        assert -1.0 <= v < 1.0


def test_random_wrapper():
    rnd = Random("wrapper")
    assert isinstance(rnd.int(10), int)
    assert 0 <= rnd.int(10) <= 10
    assert 0.0 <= rnd.float(1.0) < 1.0
    assert 0.0 <= rnd.random() < 1.0
    assert rnd.select([9, 8, 7]) in (9, 8, 7)


def test_config_values_present():
    assert config.TRACK_MAXIMUM_SCROLL_SPEED == 35
    assert config.TRACK_MAXIMUM_TRAVEL_DISTANCE == 175
    assert config.CROWD_ANIMATION_VARIATIONS == 5
    assert config.NTTRACK_VERSION == "7.1.0"


def test_reference_vectors():
    # Verified byte-for-byte against random-seed@0.3.0 (Node) for seed "hello".
    rng = Uheprng("hello")
    assert [rng.random() for _ in range(5)] == [
        0.9439915573427525,
        0.5987379889279894,
        0.32604379789089954,
        0.24089779769152553,
        0.10660342364253228,
    ]
    r2 = Uheprng("hello")
    assert [r2.int_between(0, 10) for _ in range(5)] == [10, 6, 3, 2, 1]
    r3 = Uheprng("hello")
    assert [r3.float_between(-1, 1) for _ in range(5)] == [
        0.8879831146855051,
        0.1974759778559787,
        -0.3479124042182009,
        -0.5182044046169489,
        -0.7867931527149354,
    ]


def test_generate_deterministic():
    a = generate_track(seed="run").to_dict()
    b = generate_track(seed="run").to_dict()
    assert a == b


def test_generate_shape():
    layout = generate_track(seed="run", lane_count=3, segment_count=12)
    d = layout.to_dict()
    assert d["lane_count"] == 3
    assert len(d["segments"]) == 12
    assert len(d["cars"]) >= 1
    # segments partition the length (approximately; segment lengths vary)
    assert all(seg["length"] > 0 for seg in d["segments"])
    assert all(0 <= sc["variation"] < config.CROWD_ANIMATION_VARIATIONS for sc in d["scenery"])


def test_json_roundtrip():
    layout = generate_track(seed="roundtrip")
    data = json.loads(json.dumps(layout.to_dict()))
    assert data["seed"] == "roundtrip"
    assert data["name"]


def test_userscript_and_preview():
    layout = generate_track(seed="ui")
    js = build_userscript(layout)
    html = build_preview_html(layout)
    assert "==UserScript==" in js
    assert "@match" in js
    assert layout.name in js
    assert "nt-track-canvas" in js
    assert "<canvas" not in html  # canvas is created by JS
    assert layout.name in html
    assert "requestAnimationFrame" in html


def test_2d_preview():
    layout = generate_track(seed="ui")
    html = build_2d_preview_html(layout)
    assert "<canvas" not in html  # canvas is created by JS
    assert layout.name in html
    assert "requestAnimationFrame" in html
    assert "offsetPath" in html
    # the 2D view integrates curvature into a closed circuit
    assert "gapX" in html
    # cars are driven by the vendored nt-animator bundle
    assert "nt-animator.js" in html
    assert "window.NT_ANIMATOR" in html
    assert "PIXI" in html
    assert "animate" in html


def test_animator_bundle_vendored():
    assert ANIMATOR_BUNDLE.exists()
    data = ANIMATOR_BUNDLE.read_bytes()
    assert len(data) > 100_000
    assert b"parcelRequire" in data
    assert b"nt-animator" in data


def test_resolve_car_by_id_and_key():
    from ntrack.carpreview import CarDataError, resolve_car

    assert resolve_car("372") == ("wflower", "372")
    assert resolve_car("wflower") == ("wflower", "")
    with pytest.raises(CarDataError):
        resolve_car("no-such-car")


def test_car_preview_page():
    from ntrack.carpreview import build_car_preview_html, car_sheet_path

    assert car_sheet_path("wflower").exists()
    html = build_car_preview_html("wflower")
    assert "nt-animator.js" in html
    assert "window.NT_ANIMATOR" in html
    assert "data:image/png;base64," in html
    assert "wflower" in html
    assert "NT.Animator" in html
    assert "installSheet" in html
    assert "The Wildflower 1 Million" in html
    # the manifest slice must only carry the requested car
    assert '"cars":{"wflower"' in html.replace(" ", "")


def test_car_index_and_gallery():
    from ntrack.carpreview import build_car_gallery_html, car_index

    index = car_index()
    keys = {item["key"] for item in index}
    assert "wflower" in keys
    assert "amg" in keys
    assert all(item["name"] for item in index)

    wflower = next(item for item in index if item["key"] == "wflower")
    assert "372" in wflower["ids"]

    html = build_car_gallery_html()
    assert "nt-animator.js" in html
    assert 'id="nt-car-picker"' in html
    assert "loadCar" in html
    assert "clearSheet" in html
    # every animated car with a spritesheet is inlined
    for key in ("wflower", "amg", "robo"):
        assert f'"png":"data:image/png;base64,' in html
        assert f'"cars/{key}"' in html.replace(" ", "")