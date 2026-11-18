"""JavaScript half of the hybrid.

Python cannot run inside a browser page, so the rendering layer stays in
JavaScript. This module turns a :class:`ntrack.track.TrackLayout` into:

* ``build_preview_html`` -- a standalone HTML file that animates the track with a
  dependency-free pseudo-3D canvas renderer. Open it directly in a browser.
* ``build_userscript`` -- a Tampermonkey/Greasemonkey userscript that renders the
  same layout. The live Nitro Type adapter is stubbed and clearly marked, since
  wiring it requires the site's internals.

Both share :data:`RENDERER_JS` so the preview and the userscript never drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .track import TrackLayout

# Vendored browser bundle of https://github.com/teachingcom/nt-animator.
# Copied next to the 2D preview so it can be loaded with a plain <script> tag.
ANIMATOR_BUNDLE = Path(__file__).with_name("vendor") / "nt-animator.js"

# The renderer is plain ES5-ish JavaScript with two injected tokens.
RENDERER_JS = r"""
(function () {
  "use strict";

  var TRACK = __TRACK_JSON__;
  var CFG = __CFG_JSON__;

  var canvas = document.getElementById("nt-track-canvas");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.id = "nt-track-canvas";
    canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;display:block;background:#0b0e17;z-index:2147483647;";
    (document.body || document.documentElement).appendChild(canvas);
  }
  var ctx = canvas.getContext("2d");
  var W = 0, H = 0;

  function resize() {
    W = canvas.clientWidth || window.innerWidth || 800;
    H = canvas.clientHeight || window.innerHeight || 600;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  window.addEventListener("resize", resize);
  resize();

  var ROAD_WIDTH = 2000;          // world units across the road
  var CAM_HEIGHT = ROAD_WIDTH / 2;
  var CAM_DEPTH = 0.84;           // 1 / tan(fov / 2)
  var SEG_SCALE = 40;             // layout units -> world units
  var DRAW_SEGMENTS = 220;        // segments drawn ahead of the camera
  var CURVE_K = 0.01;             // curvature gain for the lateral drift walk

  var segs = [];
  var z = 0;
  for (var i = 0; i < TRACK.segments.length; i++) {
    var s = TRACK.segments[i];
    segs.push({ index: i, z1: z, z2: z + s.length, curve: s.curve, band: (Math.floor(i / 3) % 2) });
    z += s.length;
  }
  var TRACK_LEN = z;
  var CAM_SPEED = TRACK_LEN / 7;  // layout units per second (~7 s per lap)

  var cars = TRACK.cars.map(function (c, i) {
    return {
      lane: c.lane, color: c.color, name: c.name, player: c.is_player,
      z: (c.distance + i * (TRACK_LEN / Math.max(1, TRACK.cars.length))) % TRACK_LEN,
      speed: 0.85 + (i % 5) * 0.06
    };
  });

  function project(worldX, worldZ, camZ) {
    var dz = (worldZ - camZ) * SEG_SCALE;
    if (dz <= 0.0001) return null;
    var scale = CAM_DEPTH / dz;
    return {
      scale: scale,
      x: Math.round(W / 2 + scale * worldX * W / 2),
      y: Math.round(H / 2 + scale * CAM_HEIGHT * H / 2),
      w: Math.round(scale * ROAD_WIDTH * W / 2)
    };
  }

  // Walk the segments ahead of the camera, integrating curvature so the road
  // bends continuously instead of snapping at segment (and lap) boundaries.
  function buildSlices(camZ) {
    var base = 0, i;
    for (i = 0; i < segs.length; i++) { if (segs[i].z1 <= camZ) base = i; else break; }
    var out = [];
    var x = 0, dx = 0;
    for (var n = 1; n <= DRAW_SEGMENTS; n++) {
      var sg = segs[(base + n) % segs.length];
      var z1 = sg.z1, z2 = sg.z2;
      while (z1 < camZ) { z1 += TRACK_LEN; z2 += TRACK_LEN; }
      x += dx * (sg.z2 - sg.z1) * SEG_SCALE;
      dx += sg.curve * CURVE_K;
      out.push({ z1: z1, z2: z2, off: x, band: sg.band });
    }
    return out;
  }

  function sliceAt(slices, zz) {
    for (var i = 0; i < slices.length; i++) {
      if (zz >= slices[i].z1 && zz < slices[i].z2) return slices[i];
    }
    return slices[slices.length - 1];
  }

  function poly(x1, y1, x2, y2, x3, y3, x4, y4, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.lineTo(x3, y3);
    ctx.lineTo(x4, y4);
    ctx.closePath();
    ctx.fill();
  }

  function drawSegment(x1, y1, w1, x2, y2, w2, color) {
    ctx.fillStyle = color.grass;
    ctx.fillRect(0, y2, W, y1 - y2 + 1);
    poly(x1 - w1 * 1.12, y1, x1 + w1 * 1.12, y1, x2 + w2 * 1.12, y2, x2 - w2 * 1.12, y2, color.rumble);
    poly(x1 - w1, y1, x1 + w1, y1, x2 + w2, y2, x2 - w2, y2, color.road);
    if (color.lane) {
      var lw1 = Math.max(1, w1 * 0.02), lw2 = Math.max(1, w2 * 0.02);
      for (var l = 1; l < TRACK.lane_count; l++) {
        var lx1 = x1 - w1 + (2 * w1) * (l / TRACK.lane_count);
        var lx2 = x2 - w2 + (2 * w2) * (l / TRACK.lane_count);
        poly(lx1 - lw1, y1, lx1 + lw1, y1, lx2 + lw2, y2, lx2 - lw2, y2, color.lane);
      }
    }
  }

  var COLORS = {
    light: { road: "#3b3f4a", grass: "#1f8a4c", rumble: "#e8e8e8", lane: "#d9d9d9" },
    dark: { road: "#33373f", grass: "#187a42", rumble: "#c23b3b", lane: "#d9d9d9" }
  };

  var camZ = 0;
  var last = (window.performance && performance.now) ? performance.now() : Date.now();

  function frame(now) {
    var dt = Math.min(0.05, (now - last) / 1000);
    last = now;

    camZ = (camZ + CAM_SPEED * dt) % TRACK_LEN;
    for (var i = 0; i < cars.length; i++) {
      cars[i].z = (cars[i].z + CAM_SPEED * dt * cars[i].speed) % TRACK_LEN;
    }

    var sky = ctx.createLinearGradient(0, 0, 0, H / 2);
    sky.addColorStop(0, "#0b0e17");
    sky.addColorStop(1, "#243b55");
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, W, H);

    var slices = buildSlices(camZ);

    for (var n = slices.length - 1; n >= 0; n--) {
      var sl = slices[n];
      var p1 = project(sl.off, sl.z1, camZ);
      var p2 = project(sl.off, sl.z2, camZ);
      if (!p1 || !p2) continue;
      drawSegment(p1.x, p1.y, p1.w, p2.x, p2.y, p2.w, COLORS[sl.band ? "dark" : "light"]);
    }

    drawSprites(slices, camZ);

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 20px system-ui, sans-serif";
    ctx.fillText(TRACK.name, 20, 34);
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillStyle = "#9fb3c8";
    ctx.fillText("seed: " + TRACK.seed + "   lanes: " + TRACK.lane_count + "   nt-track-py " + CFG.version, 20, 54);

    requestAnimationFrame(frame);
  }

  function drawSprites(slices, camZ) {
    var items = [];
    var i, sc, seg, z, side, p, sl;

    for (i = 0; i < TRACK.scenery.length; i++) {
      sc = TRACK.scenery[i];
      z = sc.distance;
      while (z < camZ) z += TRACK_LEN;
      sl = sliceAt(slices, z);
      side = sc.side === "left" ? -1 : 1;
      p = project(sl.off + side * ROAD_WIDTH * 1.25, z, camZ);
      if (p) items.push({ z: z, kind: "scenery", p: p });
    }

    var laneW = (ROAD_WIDTH * 2) / TRACK.lane_count;
    for (i = 0; i < cars.length; i++) {
      var c = cars[i];
      z = c.z;
      while (z < camZ) z += TRACK_LEN;
      sl = sliceAt(slices, z);
      var worldX = sl.off - ROAD_WIDTH + laneW * (c.lane + 0.5);
      p = project(worldX, z, camZ);
      if (p) items.push({ z: z, kind: "car", p: p, car: c });
    }

    items.sort(function (a, b) { return b.z - a.z; });

    for (i = 0; i < items.length; i++) {
      var it = items[i];
      p = it.p;
      if (it.kind === "car") {
        var cw = Math.max(2, p.w * 0.18);
        var ch = cw * 0.6;
        ctx.fillStyle = it.car.color;
        ctx.fillRect(p.x - cw / 2, p.y - ch, cw, ch);
        if (it.car.player) {
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth = 2;
          ctx.strokeRect(p.x - cw / 2, p.y - ch, cw, ch);
        }
      } else {
        var sw = Math.max(2, p.w * 0.5);
        var sh = sw * 0.5;
        ctx.fillStyle = "rgba(255,255,255,0.85)";
        ctx.fillRect(p.x - sw / 2, p.y - sh, sw, sh);
        ctx.fillStyle = "rgba(0,0,0,0.35)";
        ctx.fillRect(p.x - sw / 2, p.y - sh, sw, sh * 0.25);
      }
    }
  }

  requestAnimationFrame(frame);

  // --- Nitro Type adapter (live-site integration) ----------------------
  // The preview above runs standalone. To drive the real Nitro Type race view
  // these hooks must be wired to the site's Phaser game instance / scene. They
  // are intentionally no-ops so the bundle loads without the site present.
  var NTTRACK = {
    version: CFG.version,
    layout: TRACK,
    findGame: function () { return null; },        // TODO: locate window game
    onRaceStart: function () { },                   // TODO: mount into Phaser scene
    destroy: function () { }                        // TODO: remove canvas / listeners
  };
  if (typeof window !== "undefined") window.NTTRACK = NTTRACK;
})();
"""


RENDERER_2D_JS = r"""
(function () {
  "use strict";

  var TRACK = __TRACK_JSON__;
  var CFG = __CFG_JSON__;

  var canvas = document.getElementById("nt-track-canvas");
  if (!canvas) {
    canvas = document.createElement("canvas");
    canvas.id = "nt-track-canvas";
    canvas.style.cssText = "position:fixed;inset:0;width:100%;height:100%;display:block;background:#0b0e17;z-index:2147483647;";
    (document.body || document.documentElement).appendChild(canvas);
  }
  var ctx = canvas.getContext("2d");
  var W = 0, H = 0, DPR = 1;

  // --- centre line: integrate each segment's curvature -----------------
  // The turn per unit length is normalised so the loop closes on itself.
  var segs = TRACK.segments;
  var i, totalCurve = 0;
  for (i = 0; i < segs.length; i++) totalCurve += segs[i].curve * segs[i].length;
  var TURN = Math.abs(totalCurve) > 1e-6 ? (Math.PI * 2) / totalCurve : 0;

  var pts = [];
  var x = 0, y = 0, heading = -Math.PI / 2, dist = 0;
  pts.push({ x: x, y: y, s: 0 });
  for (i = 0; i < segs.length; i++) {
    heading += segs[i].curve * segs[i].length * TURN;
    x += Math.cos(heading) * segs[i].length;
    y += Math.sin(heading) * segs[i].length;
    dist += segs[i].length;
    pts.push({ x: x, y: y, s: dist });
  }
  // Drop the duplicated closing point so offset paths stay clean.
  pts.pop();

  // Distribute the closure error along the lap so the circuit actually joins up.
  var gapX = x, gapY = y;
  for (i = 0; i < pts.length; i++) {
    var f = dist > 0 ? pts[i].s / dist : 0;
    pts[i].x -= gapX * f;
    pts[i].y -= gapY * f;
  }

  var minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (i = 0; i < pts.length; i++) {
    if (pts[i].x < minX) minX = pts[i].x;
    if (pts[i].x > maxX) maxX = pts[i].x;
    if (pts[i].y < minY) minY = pts[i].y;
    if (pts[i].y > maxY) maxY = pts[i].y;
  }

  var ROAD_W = Math.max(1, Math.max(maxX - minX, maxY - minY) * 0.08);
  var LANE_W = ROAD_W / TRACK.lane_count;
  var CAR_SPEED = dist / 14;

  var view = { scale: 1, ox: 0, oy: 0 };

  function resize() {
    W = canvas.clientWidth || window.innerWidth || 800;
    H = canvas.clientHeight || window.innerHeight || 600;
    DPR = window.devicePixelRatio || 1;
    canvas.width = W * DPR;
    canvas.height = H * DPR;
    computeView();
    if (!carLayerTried) {
      carLayerTried = true;
      carLayer = NT ? createCarLayer(NT) : null;
    }
    if (carLayer) carLayer.resize();
  }

  function computeView() {
    var pad = 48;
    var spanX = Math.max(1e-6, maxX - minX);
    var spanY = Math.max(1e-6, maxY - minY);
    view.scale = Math.min((W - pad * 2) / spanX, (H - pad * 2) / spanY);
    view.ox = (W - spanX * view.scale) / 2 - minX * view.scale;
    view.oy = (H - spanY * view.scale) / 2 - minY * view.scale;
  }

  window.addEventListener("resize", resize);

  function pointAt(s) {
    var v = ((s % dist) + dist) % dist;
    for (var k = 0; k < pts.length; k++) {
      var a = pts[k], b = pts[(k + 1) % pts.length];
      var span = b.s - a.s;
      if (span <= 0) span = dist - a.s;
      var end = a.s + span;
      if (v >= a.s && v < end) {
        var t = span > 0 ? (v - a.s) / span : 0;
        return {
          x: a.x + (b.x - a.x) * t,
          y: a.y + (b.y - a.y) * t,
          a: Math.atan2(b.y - a.y, b.x - a.x)
        };
      }
    }
    var last = pts[0];
    return { x: last.x, y: last.y, a: 0 };
  }

  function offsetPath(o) {
    var out = [];
    for (var k = 0; k < pts.length; k++) {
      var p0 = pts[(k - 1 + pts.length) % pts.length];
      var p1 = pts[(k + 1) % pts.length];
      var dx = p1.x - p0.x, dy = p1.y - p0.y;
      var len = Math.sqrt(dx * dx + dy * dy) || 1;
      out.push({ x: pts[k].x - (dy / len) * o, y: pts[k].y + (dx / len) * o });
    }
    return out;
  }

  function trace(path, close) {
    ctx.beginPath();
    ctx.moveTo(path[0].x, path[0].y);
    for (var k = 1; k < path.length; k++) ctx.lineTo(path[k].x, path[k].y);
    if (close !== false) ctx.closePath();
  }

  function strokePath(path, width, color, dash) {
    trace(path);
    ctx.lineWidth = width;
    ctx.strokeStyle = color;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.setLineDash(dash || []);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  var roadEdge = offsetPath(ROAD_W * 0.54);

  var lanePaths = [];
  for (var l = 1; l < TRACK.lane_count; l++) {
    lanePaths.push(offsetPath(-ROAD_W / 2 + LANE_W * l));
  }

  function drawStartLine() {
    var p = pointAt(0);
    var cols = 8, w = ROAD_W / cols, h = ROAD_W * 0.10;
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(p.a);
    for (var r = 0; r < 2; r++) {
      for (var c = 0; c < cols; c++) {
        ctx.fillStyle = ((r + c) % 2 === 0) ? "#f2f4f8" : "#20242e";
        ctx.fillRect(-h + r * h, -ROAD_W / 2 + c * w, h, w);
      }
    }
    ctx.restore();
  }

  // --- nt-animator car layer -------------------------------------------
  // Cars are PIXI sprites whose pace is animated by nt-animator. When the
  // bundle is missing (or PIXI cannot start) the renderer falls back to the
  // plain rectangles below.
  var NT = window.NT_ANIMATOR || null;

  var cars = TRACK.cars.map(function (c, idx) {
    var speed = 0.9 + (idx % 5) * 0.04;
    var car = {
      lane: c.lane, color: c.color, name: c.name, player: c.is_player,
      s: c.distance, speed: speed, state: { v: speed }, anim: null
    };
    if (NT && NT.animate) {
      car.anim = NT.animate({
        targets: car.state,
        from: { v: speed * 0.8 },
        to: { v: speed * 1.2 },
        duration: 1500 + idx * 230,
        loop: true,
        direction: "alternate",
        easing: "easeInOutSine",
        auto: false
      });
    }
    return car;
  });

  var carLayer = null;
  var carLayerTried = false;

  function createCarLayer(NT) {
    try {
      var PIXI = NT.PIXI;
      if (!PIXI || !PIXI.CanvasRenderer) return null;
      var renderer = new PIXI.CanvasRenderer({ width: W, height: H, transparent: true, resolution: DPR });
      var view = renderer.view;
      view.id = "nt-track-cars";
      view.style.cssText = "position:fixed;inset:0;width:100%;height:100%;display:block;pointer-events:none;z-index:2147483647;";
      (document.body || document.documentElement).appendChild(view);

      var stage = new PIXI.Container();
      var sprites = cars.map(function (car) {
        var sprite = new PIXI.Sprite(carTexture(PIXI, car.color, car.player));
        sprite.anchor.set(0.5);
        stage.addChild(sprite);
        return sprite;
      });

      return {
        renderer: renderer,
        sprites: sprites,
        resize: function () { renderer.resize(W, H); },
        render: function () { renderer.render(stage); }
      };
    } catch (err) {
      if (window.console && console.warn) console.warn("nt-animator car layer unavailable:", err);
      return null;
    }
  }

  function carTexture(PIXI, color, isPlayer) {
    var c = document.createElement("canvas");
    c.width = 64;
    c.height = 32;
    var g = c.getContext("2d");
    g.fillStyle = "#14171f";
    g.fillRect(12, 4, 12, 6);
    g.fillRect(12, 22, 12, 6);
    g.fillRect(40, 4, 12, 6);
    g.fillRect(40, 22, 12, 6);
    g.fillStyle = color;
    g.beginPath();
    if (g.roundRect) g.roundRect(4, 8, 56, 16, 5);
    else g.rect(4, 8, 56, 16);
    g.fill();
    g.fillStyle = "rgba(12,16,24,0.85)";
    g.fillRect(24, 11, 14, 10);
    g.fillStyle = "rgba(255,255,255,0.35)";
    g.fillRect(52, 11, 6, 10);
    if (isPlayer) {
      g.strokeStyle = "#ffffff";
      g.lineWidth = 2;
      g.strokeRect(3, 7, 58, 18);
    }
    return PIXI.Texture.from(c);
  }

  var scenery = TRACK.scenery.map(function (sc) {
    return { s: sc.distance, side: sc.side === "left" ? -1 : 1, variation: sc.variation };
  });

  var last = (window.performance && performance.now) ? performance.now() : Date.now();

  function frame(now) {
    var dt = Math.min(0.05, (now - last) / 1000);
    last = now;

    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.fillStyle = "#0b0e17";
    ctx.fillRect(0, 0, W, H);

    ctx.setTransform(view.scale * DPR, 0, 0, view.scale * DPR, view.ox * DPR, view.oy * DPR);

    strokePath(roadEdge, ROAD_W * 1.12, "#e8e8e8");
    strokePath(roadEdge, ROAD_W * 1.00, "#3b3f4a");
    for (var l = 0; l < lanePaths.length; l++) {
      strokePath(lanePaths[l], Math.max(0.35, ROAD_W * 0.012), "rgba(217,217,217,0.55)", [ROAD_W * 0.22, ROAD_W * 0.20]);
    }

    for (var s = 0; s < scenery.length; s++) {
      var sc = scenery[s];
      var sp = pointAt(sc.s);
      var nx = -Math.sin(sp.a), ny = Math.cos(sp.a);
      var off = sc.side * ROAD_W * 0.72;
      var sw = ROAD_W * 0.10, sh = ROAD_W * 0.10;
      ctx.fillStyle = sc.variation % 2 === 0 ? "#9fb3c8" : "#6b7f94";
      ctx.fillRect(sp.x + nx * off - sw / 2, sp.y + ny * off - sh / 2, sw, sh);
    }

    drawStartLine();

    for (var c2 = 0; c2 < cars.length; c2++) {
      var car = cars[c2];
      if (car.anim) car.anim.tick();
      car.s = (car.s + CAR_SPEED * (car.anim ? car.state.v : car.speed) * dt) % dist;
      var cp = pointAt(car.s);
      var laneOff = -ROAD_W / 2 + LANE_W * (car.lane + 0.5);
      var cnx = -Math.sin(cp.a), cny = Math.cos(cp.a);
      var wx = cp.x + cnx * laneOff;
      var wy = cp.y + cny * laneOff;

      if (carLayer) {
        var sprite = carLayer.sprites[c2];
        var cwPx = Math.max(6, ROAD_W * 0.22 * view.scale);
        sprite.position.set(wx * view.scale + view.ox, wy * view.scale + view.oy);
        sprite.width = cwPx;
        sprite.height = cwPx * 0.5;
        sprite.rotation = cp.a;
      } else {
        var cw = ROAD_W * 0.20, ch = Math.max(ROAD_W * 0.03, LANE_W * 0.62);
        ctx.save();
        ctx.translate(wx, wy);
        ctx.rotate(cp.a);
        ctx.fillStyle = car.color;
        ctx.fillRect(-cw / 2, -ch / 2, cw, ch);
        if (car.player) {
          ctx.lineWidth = Math.max(0.3, ROAD_W * 0.012);
          ctx.strokeStyle = "#ffffff";
          ctx.strokeRect(-cw / 2, -ch / 2, cw, ch);
        }
        ctx.restore();
      }
    }

    if (carLayer) carLayer.render();

    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 20px system-ui, sans-serif";
    ctx.fillText(TRACK.name, 20, 34);
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillStyle = "#9fb3c8";
    ctx.fillText("seed: " + TRACK.seed + "   lanes: " + TRACK.lane_count + "   nt-track-py " + CFG.version, 20, 54);

    requestAnimationFrame(frame);
  }

  resize();
  requestAnimationFrame(frame);

  // --- Nitro Type adapter (live-site integration) ----------------------
  var NTTRACK = {
    version: CFG.version,
    layout: TRACK,
    findGame: function () { return null; },        // TODO: locate window game
    onRaceStart: function () { },                   // TODO: mount into Phaser scene
    destroy: function () { }                        // TODO: remove canvas / listeners
  };
  if (typeof window !== "undefined") window.NTTRACK = NTTRACK;
})();
"""


def _inject(template: str, layout: TrackLayout) -> str:
    track_json = json.dumps(layout.to_dict(), separators=(",", ":"))
    cfg_json = json.dumps({"version": config.NTTRACK_VERSION})
    return template.replace("__TRACK_JSON__", track_json).replace("__CFG_JSON__", cfg_json)


def _renderer_js(layout: TrackLayout) -> str:
    return _inject(RENDERER_JS, layout)


def _renderer_2d_js(layout: TrackLayout) -> str:
    return _inject(RENDERER_2D_JS, layout)


# nt-animator is a Parcel CommonJS bundle, so the page must provide `module`
# and a `require` shim before it is loaded. Its exports land on module.exports.
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


def _preview_html(js: str, title: str | None, layout: TrackLayout, with_animator: bool = False) -> str:
    title = title or f"{layout.name} - nt-track-py preview"
    vendor = ANIMATOR_SHIM if with_animator else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #0b0e17; overflow: hidden; }}
</style>
</head>
<body>
{vendor}
<script>
{js}
</script>
</body>
</html>
"""


def build_preview_html(layout: TrackLayout, title: str | None = None) -> str:
    """Return a self-contained HTML page that animates the layout in pseudo-3D."""
    return _preview_html(_renderer_js(layout), title, layout)


def build_2d_preview_html(layout: TrackLayout, title: str | None = None) -> str:
    """Return a top-down (2D) HTML page for the layout.

    The page loads ``nt-animator.js`` (vendored from teachingcom/nt-animator)
    and uses it to animate the cars. When that bundle is not next to the page,
    the renderer silently falls back to plain car rectangles.
    """
    return _preview_html(_renderer_2d_js(layout), title, layout, with_animator=True)


def build_userscript(layout: TrackLayout) -> str:
    """Return a Tampermonkey/Greasemonkey userscript for the layout."""
    js = _renderer_js(layout)
    header = f"""// ==UserScript==
// @name         nt-track-py ({layout.name})
// @namespace    https://github.com/teachingcom/nt-track
// @version      {config.NTTRACK_VERSION}
// @description  Python-generated track layout for Nitro Type (nt-track-py)
// @match        https://www.nitrotype.com/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==

"""
    return header + js