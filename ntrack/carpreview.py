"""Build a hover-animated Nitro Type car preview page.

The page is the standalone version of what the Nitro Type data archive does on
hover: it composes a car with nt-animator and renders it with PIXI.

Data comes from the vendored animation pack in ``ntrack/vendor``:

* ``car-data.json`` - nt-animator manifest (compositions + spritesheet frames)
* ``car-ids.json``  - Nitro Type car id -> animation asset key
* ``cars/<key>.png`` - spritesheets that ship with this repo

Everything the page needs (manifest + spritesheet) is inlined into the HTML, so
the only external file is ``nt-animator.js``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

VENDOR = Path(__file__).with_name("vendor")
CAR_DATA_PATH = VENDOR / "car-data.json"
CAR_IDS_PATH = VENDOR / "car-ids.json"
CAR_NAMES_PATH = VENDOR / "car-names.json"
CAR_SHEETS_DIR = VENDOR / "cars"

ANIMATOR_SRC = "https://nitrotype.info/assets/animated"


class CarDataError(RuntimeError):
    """Raised when the vendored car animation data is missing or incomplete."""


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise CarDataError(f"missing vendored data file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_car_ids() -> dict[str, str]:
    """Return the ``{car id: asset key}`` map (as strings)."""
    return _load_json(CAR_IDS_PATH)


def load_car_names() -> dict[str, dict]:
    """Return the ``{car id: {key, name}}`` map from the Nitro Type bootstrap."""
    if not CAR_NAMES_PATH.exists():
        return {}
    return _load_json(CAR_NAMES_PATH)


def car_sheet_path(asset_key: str) -> Path:
    return CAR_SHEETS_DIR / f"{asset_key}.png"


def car_index() -> list[dict]:
    """List every animated car: ``[{key, name, ids}]`` sorted by name."""
    names = load_car_names()
    ids_by_key: dict[str, list[str]] = {}
    for car_id, key in load_car_ids().items():
        ids_by_key.setdefault(key, []).append(car_id)

    data = _load_json(CAR_DATA_PATH)
    index = []
    for key in data.get("cars", {}):
        label = key
        ids = sorted(ids_by_key.get(key, []), key=int)
        for car_id in ids:
            entry = names.get(car_id)
            if entry and entry.get("name"):
                label = f"{entry['name']}"
                break
        index.append({"key": key, "name": label, "ids": ids})
    index.sort(key=lambda item: (item["name"] or "").lower())
    return index


def resolve_car(ref: str) -> tuple[str, str]:
    """Resolve ``"372"`` or ``"wflower"`` to ``(asset_key, car_id)``.

    ``car_id`` is ``""`` when the reference is already an asset key.
    """
    ref = (ref or "").strip()
    if not ref:
        raise CarDataError("no car given")

    ids = load_car_ids()
    if ref in ids:
        return ids[ref], ref

    # asset keys are lowercase words; accept them directly
    data = _load_json(CAR_DATA_PATH)
    if ref in data.get("cars", {}):
        return ref, ""

    raise CarDataError(
        f"unknown car {ref!r}: pass a Nitro Type car id (e.g. 372) or an asset key (e.g. wflower)"
    )


def car_manifest(asset_key: str) -> dict:
    """Return the manifest slice needed to compose a single car."""
    data = _load_json(CAR_DATA_PATH)
    cars = data.get("cars", {})
    if asset_key not in cars:
        raise CarDataError(
            f"no animation data for car {asset_key!r}: this Nitro Type car has no "
            "published animation. Pick one with data (see ntrack/vendor/car-data.json)."
        )

    sheets = data.get("spritesheets", {})
    sheet = sheets.get(f"cars/{asset_key}")
    if not sheet:
        raise CarDataError(f"no spritesheet frames for car {asset_key!r}")

    return {
        "version": data.get("version", "1"),
        "cars": {asset_key: cars[asset_key]},
        "spritesheets": {f"cars/{asset_key}": sheet},
    }


def car_sheet_data_url(asset_key: str) -> str:
    """Return the car spritesheet as a ``data:`` URL (keeps canvas untainted)."""
    path = car_sheet_path(asset_key)
    if not path.exists():
        raise CarDataError(
            f"missing spritesheet for {asset_key!r}: {path}\n"
            f"download it from {ANIMATOR_SRC}/cars/{asset_key}.png"
        )
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


PAGE_SCRIPT = r"""
(function () {
  "use strict";

  var CAR_KEY = __CAR_KEY__;
  var CAR_NAME = __CAR_NAME__;
  var MANIFEST = __MANIFEST__;
  var CAR_PNG = __CAR_PNG__;

  var hud = document.getElementById("nt-car-hud");
  var host = document.getElementById("nt-car-stage");

  function say(text) {
    if (hud) hud.textContent = text;
  }

  var NT = window.NT_ANIMATOR;
  if (!NT || !NT.PIXI) {
    say("nt-animator.js not found next to this page");
    return;
  }
  var PIXI = NT.PIXI;

  var W = 1, H = 1, DPR = 1;
  var car = null;
  var last = 0;

  // --- renderer ---------------------------------------------------------
  function createRenderer() {
    var opts = {
      width: W, height: H, transparent: true, antialias: true,
      resolution: DPR, autoDensity: true
    };
    try {
      if (PIXI.utils && PIXI.utils.isWebGLSupported && PIXI.utils.isWebGLSupported()) {
        return new PIXI.Renderer(opts);
      }
    } catch (err) { /* fall through to canvas */ }
    try {
      return new PIXI.CanvasRenderer(opts);
    } catch (err) {
      return null;
    }
  }

  var renderer = null;

  // --- stage ------------------------------------------------------------
  var stage = new PIXI.Container();
  stage.movement = 0.56;
  stage.base_speed = 0.56;
  stage.normalized_pointer_x = 0.5;
  stage.normalized_pointer_y = 0.5;
  stage.center_normalized_pointer_x = 0;
  stage.center_normalized_pointer_y = 0;
  stage.current_pointer_x = 0;
  stage.current_pointer_y = 0;
  stage.isPlayerRoot = true;

  function resize() {
    W = host.clientWidth || window.innerWidth || 800;
    H = host.clientHeight || window.innerHeight || 600;
    DPR = Math.max(1, window.devicePixelRatio || 1);
    if (!renderer) {
      renderer = createRenderer();
      if (!renderer) {
        say("no renderer available");
        return;
      }
      renderer.view.style.cssText =
        "position:absolute;inset:0;width:100%;height:100%;display:block;";
      host.appendChild(renderer.view);
    }
    renderer.resize(W, H);
    layout();
  }

  function layout() {
    if (!car) return;
    var b = car.getLocalBounds();
    if (!b || b.width <= 0 || b.height <= 0) return;
    var pad = Math.min(120, Math.min(W, H) * 0.12);
    var s = Math.min((W - pad * 2) / b.width, (H - pad * 2) / b.height);
    car.scale.set(s);
    car.x = W / 2 - (b.x + b.width / 2) * s;
    car.y = H / 2 - (b.y + b.height / 2) * s;
  }

  function onPointerMove(event) {
    var rect = renderer ? renderer.view.getBoundingClientRect() : { left: 0, top: 0, width: W, height: H };
    var nx = (event.clientX - rect.left) / Math.max(1, rect.width);
    var ny = (event.clientY - rect.top) / Math.max(1, rect.height);
    nx = Math.max(0, Math.min(1, nx));
    ny = Math.max(0, Math.min(1, ny));
    stage.normalized_pointer_x = nx;
    stage.normalized_pointer_y = ny;
    stage.center_normalized_pointer_x = 2 * nx - 1;
    stage.center_normalized_pointer_y = 2 * ny - 1;
    stage.current_pointer_x = nx * W;
    stage.current_pointer_y = ny * H;
  }

  window.addEventListener("resize", resize);
  window.addEventListener("mousemove", onPointerMove, { passive: true });

  function frame(now) {
    var dt = last ? Math.min(2, Math.max(0.1, (now - last) / 16.6667)) : 1;
    last = now;
    if (car && typeof car.update === "function") car.update(dt);
    if (renderer) renderer.render(stage);
    requestAnimationFrame(frame);
  }

  // --- spritesheet ------------------------------------------------------
  // nt-animator would normally fetch <baseUrl>cars/<key>.png. We already have
  // the image, so slice it into textures and mark the sheet as ready.
  function installSheet(animator, sheetId, image, frames) {
    var base = PIXI.Texture.from(image);
    var sheet = { hasPng: true, hasJpg: false, __initialized__: true };
    for (var name in frames) {
      var f = frames[name];
      if (!Array.isArray(f) || f.length < 4) continue;
      var texture = new PIXI.Texture(base, new PIXI.Rectangle(f[0], f[1], f[2], f[3]));
      texture.identity = name;
      sheet[name] = texture;
    }
    animator.manifest.spritesheets[sheetId] = sheet;
    return sheet;
  }

  function boot() {
    resize();
    requestAnimationFrame(frame);

    var animator;
    try {
      animator = new NT.Animator(MANIFEST, { baseUrl: "", seed: 20260118 });
    } catch (err) {
      say("failed to start nt-animator: " + err);
      return;
    }

    var sheetId = "cars/" + CAR_KEY;
    var img = new Image();
    img.onload = function () {
      installSheet(animator, sheetId, img, MANIFEST.spritesheets[sheetId]);
      animator.create(sheetId)
        .then(function (displayObject) {
          car = displayObject;
          stage.addChild(car);
          layout();
          say(CAR_NAME);
        })
        .catch(function (err) {
          say("failed to compose " + sheetId + ": " + err);
        });
    };
    img.onerror = function () {
      say("failed to load the car spritesheet");
    };
    img.src = CAR_PNG;
  }

  boot();
})();
"""


ANIMATOR_SHIM = """<script>
window.module = window.module || { exports: {} };
window.require = window.require || function (id) {
  if (id === "url") {
    return {
      parse: function (u) { return { protocol: "", host: "", pathname: String(u), hash: "", search: "", query: {} }; },
      format: function (o) { return String((o && o.pathname) || ""); },
      resolve: function (a, b) { return String(b); }
    };
  }
  return {};
};
</script>
<script src="nt-animator.js"></script>
<script>window.NT_ANIMATOR = window.module.exports;</script>"""


def _json(value: object) -> str:
    """JSON for inline <script> use (safe against </script>)."""
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/")


def car_label(asset_key: str) -> str:
    """Human label for a car: ``"372 - The Wildflower 1 Million"``."""
    names = load_car_names()
    for car_id, key in load_car_ids().items():
        if key == asset_key:
            entry = names.get(car_id) or {}
            name = entry.get("name")
            return f"{car_id} - {name}" if name else car_id
    return asset_key


def build_car_preview_html(asset_key: str, title: str | None = None) -> str:
    """Return a standalone page that animates a single car on hover.

    The page inlines the car composition, its spritesheet frames and the
    spritesheet image itself, so the only external file is ``nt-animator.js``.
    """
    manifest = car_manifest(asset_key)
    png = car_sheet_data_url(asset_key)
    name = car_label(asset_key)

    js = (
        PAGE_SCRIPT.replace("__CAR_KEY__", _json(asset_key))
        .replace("__CAR_NAME__", _json(name))
        .replace("__MANIFEST__", _json(manifest))
        .replace("__CAR_PNG__", _json(png))
    )

    title = title or f"{name} - nt-track-py car preview"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #0b0e17; overflow: hidden; }}
  #nt-car-stage {{ position: fixed; inset: 0; }}
  #nt-car-hud {{
    position: fixed; left: 20px; top: 16px; z-index: 10;
    color: #ffffff; font: 600 18px system-ui, sans-serif;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6); pointer-events: none;
  }}
</style>
</head>
<body>
<div id="nt-car-stage"></div>
<div id="nt-car-hud">loading {asset_key}...</div>
{ANIMATOR_SHIM}
<script>
{js}
</script>
</body>
</html>
"""


GALLERY_SCRIPT = r"""
(function () {
  "use strict";

  var MANIFEST = __MANIFEST__;
  var CARS = __CARS__;
  var KEYS = __KEYS__;

  var hud = document.getElementById("nt-car-hud");
  var host = document.getElementById("nt-car-stage");
  var picker = document.getElementById("nt-car-picker");

  function say(text) {
    if (hud) hud.textContent = text;
  }

  var NT = window.NT_ANIMATOR;
  if (!NT || !NT.PIXI) {
    say("nt-animator.js not found next to this page");
    return;
  }
  var PIXI = NT.PIXI;

  var W = 1, H = 1, DPR = 1;
  var car = null;
  var currentSheet = null;
  var loadToken = 0;
  var last = 0;

  // --- renderer ---------------------------------------------------------
  function createRenderer() {
    var opts = {
      width: W, height: H, transparent: true, antialias: true,
      resolution: DPR, autoDensity: true
    };
    try {
      if (PIXI.utils && PIXI.utils.isWebGLSupported && PIXI.utils.isWebGLSupported()) {
        return new PIXI.Renderer(opts);
      }
    } catch (err) { /* fall through to canvas */ }
    try {
      return new PIXI.CanvasRenderer(opts);
    } catch (err) {
      return null;
    }
  }

  var renderer = null;

  // --- stage ------------------------------------------------------------
  var stage = new PIXI.Container();
  stage.movement = 0.56;
  stage.base_speed = 0.56;
  stage.normalized_pointer_x = 0.5;
  stage.normalized_pointer_y = 0.5;
  stage.center_normalized_pointer_x = 0;
  stage.center_normalized_pointer_y = 0;
  stage.current_pointer_x = 0;
  stage.current_pointer_y = 0;
  stage.isPlayerRoot = true;

  function resize() {
    W = host.clientWidth || window.innerWidth || 800;
    H = host.clientHeight || window.innerHeight || 600;
    DPR = Math.max(1, window.devicePixelRatio || 1);
    if (!renderer) {
      renderer = createRenderer();
      if (!renderer) {
        say("no renderer available");
        return;
      }
      renderer.view.style.cssText =
        "position:absolute;inset:0;width:100%;height:100%;display:block;";
      host.appendChild(renderer.view);
    }
    renderer.resize(W, H);
    layout();
  }

  function layout() {
    if (!car) return;
    var b = car.getLocalBounds();
    if (!b || b.width <= 0 || b.height <= 0) return;
    var pad = Math.min(120, Math.min(W, H) * 0.12);
    var s = Math.min((W - pad * 2) / b.width, (H - pad * 2) / b.height);
    car.scale.set(s);
    car.x = W / 2 - (b.x + b.width / 2) * s;
    car.y = H / 2 - (b.y + b.height / 2) * s;
  }

  function onPointerMove(event) {
    var rect = renderer ? renderer.view.getBoundingClientRect() : { left: 0, top: 0, width: W, height: H };
    var nx = (event.clientX - rect.left) / Math.max(1, rect.width);
    var ny = (event.clientY - rect.top) / Math.max(1, rect.height);
    nx = Math.max(0, Math.min(1, nx));
    ny = Math.max(0, Math.min(1, ny));
    stage.normalized_pointer_x = nx;
    stage.normalized_pointer_y = ny;
    stage.center_normalized_pointer_x = 2 * nx - 1;
    stage.center_normalized_pointer_y = 2 * ny - 1;
    stage.current_pointer_x = nx * W;
    stage.current_pointer_y = ny * H;
  }

  window.addEventListener("resize", resize);
  window.addEventListener("mousemove", onPointerMove, { passive: true });

  function frame(now) {
    var dt = last ? Math.min(2, Math.max(0.1, (now - last) / 16.6667)) : 1;
    last = now;
    if (car && typeof car.update === "function") car.update(dt);
    if (renderer) renderer.render(stage);
    requestAnimationFrame(frame);
  }

  // --- spritesheets -----------------------------------------------------
  // nt-animator would fetch <baseUrl>cars/<key>.png. The image is already
  // inlined, so slice it into textures and mark the sheet as ready.
  function installSheet(animator, sheetId, image, frames) {
    var base = new PIXI.BaseTexture(image);
    var sheet = { hasPng: true, hasJpg: false, __initialized__: true };
    var textures = [];
    for (var name in frames) {
      var f = frames[name];
      if (!Array.isArray(f) || f.length < 4) continue;
      var texture = new PIXI.Texture(base, new PIXI.Rectangle(f[0], f[1], f[2], f[3]));
      texture.identity = name;
      sheet[name] = texture;
      textures.push(texture);
    }
    animator.manifest.spritesheets[sheetId] = sheet;
    currentSheet = { base: base, textures: textures };
  }

  function clearSheet() {
    if (!currentSheet) return;
    for (var i = 0; i < currentSheet.textures.length; i++) {
      try { currentSheet.textures[i].destroy(false); } catch (err) { }
    }
    try { currentSheet.base.destroy(); } catch (err) { }
    currentSheet = null;
  }

  function disposeCar() {
    if (!car) return;
    try { stage.removeChild(car); } catch (err) { }
    try { if (car.dispose) car.dispose(); } catch (err) { }
    try { car.destroy({ children: true }); } catch (err) { }
    car = null;
    clearSheet();
  }

  // --- loading ----------------------------------------------------------
  function loadCar(key) {
    if (!CARS[key]) return;
    var token = ++loadToken;
    disposeCar();

    var entry = CARS[key];
    say(entry.name);

    var img = new Image();
    img.onload = function () {
      if (token !== loadToken) return;
      var animator = window.__ntAnimator;
      installSheet(animator, "cars/" + key, img, MANIFEST.spritesheets["cars/" + key]);
      animator.create("cars/" + key)
        .then(function (displayObject) {
          if (token !== loadToken) {
            try { displayObject.destroy({ children: true }); } catch (err) { }
            return;
          }
          car = displayObject;
          stage.addChild(car);
          layout();
        })
        .catch(function (err) {
          say("failed to compose " + key + ": " + err);
        });
    };
    img.onerror = function () {
      say("failed to load the spritesheet for " + key);
    };
    img.src = entry.png;
  }

  // --- picker -----------------------------------------------------------
  function fillPicker() {
    if (!picker) return;
    for (var i = 0; i < KEYS.length; i++) {
      var option = document.createElement("option");
      option.value = KEYS[i];
      option.textContent = CARS[KEYS[i]].name;
      picker.appendChild(option);
    }
    picker.addEventListener("change", function () { loadCar(picker.value); });
  }

  function boot() {
    resize();
    requestAnimationFrame(frame);
    fillPicker();

    var animator;
    try {
      animator = new NT.Animator(MANIFEST, { baseUrl: "", seed: 20260118 });
      window.__ntAnimator = animator;
    } catch (err) {
      say("failed to start nt-animator: " + err);
      return;
    }

    var initial = (location.hash || "").replace(/^#/, "");
    var key = CARS[initial] ? initial : KEYS[0];
    if (picker) picker.value = key;
    loadCar(key);
  }

  boot();
})();
"""


def build_car_gallery_html(title: str | None = None) -> str:
    """Return a page that can animate every car that has published data.

    All 114 compositions and spritesheets are inlined, so the page is a single
    self contained file (plus ``nt-animator.js``). ``cars.html#<asset key>``
    opens on a specific car.
    """
    data = _load_json(CAR_DATA_PATH)
    index = car_index()

    manifest = {
        "version": data.get("version", "1"),
        "cars": data.get("cars", {}),
        "spritesheets": data.get("spritesheets", {}),
    }

    cars = {}
    keys = []
    for item in index:
        key = item["key"]
        if not car_sheet_path(key).exists():
            continue
        cars[key] = {"name": item["name"], "png": car_sheet_data_url(key)}
        keys.append(key)

    if not cars:
        raise CarDataError(
            f"no spritesheets found in {CAR_SHEETS_DIR}; "
            f"download them from {ANIMATOR_SRC}/cars/<key>.png"
        )

    js = (
        GALLERY_SCRIPT.replace("__MANIFEST__", _json(manifest))
        .replace("__CARS__", _json(cars))
        .replace("__KEYS__", _json(keys))
    )

    title = title or "Animated Nitro Type cars - nt-track-py"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #0b0e17; overflow: hidden; }}
  #nt-car-stage {{ position: fixed; inset: 0; }}
  #nt-car-hud {{
    position: fixed; left: 20px; top: 16px; z-index: 10;
    color: #ffffff; font: 600 18px system-ui, sans-serif;
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6); pointer-events: none;
  }}
  #nt-car-picker {{
    position: fixed; left: 20px; bottom: 18px; z-index: 10;
    max-width: 320px; padding: 8px 10px; border-radius: 10px;
    background: rgba(20, 24, 34, 0.85); color: #e8ecf4;
    font: 500 14px system-ui, sans-serif; border: 1px solid #2a3142;
  }}
</style>
</head>
<body>
<div id="nt-car-stage"></div>
<div id="nt-car-hud">loading...</div>
<select id="nt-car-picker"></select>
{ANIMATOR_SHIM}
<script>
{js}
</script>
</body>
</html>
"""