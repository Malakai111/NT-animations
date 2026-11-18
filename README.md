# nt-track-py

A **hybrid Python reimplementation** of [`teachingcom/nt-track`](https://github.com/teachingcom/nt-track)
&mdash; the Track / Garage / Preview modes for Nitro Type.

The original is a browser **userscript** (JavaScript, bundled with Parcel) that
hooks into the Nitro Type web app's Phaser game and renders custom race tracks
inside the page. Python cannot execute inside a browser page, so a pure-Python
userscript is not possible. This project keeps the split honest:

| Layer | Language | What it does |
|-------|----------|--------------|
| **Layout logic** | Python | Seeded RNG, config constants, deterministic track generation |
| **Renderer** | JavaScript | Pseudo-3D canvas renderer + Nitro Type adapter stub |

Python generates a deterministic **track layout** (JSON). A tiny JavaScript
renderer draws it &mdash; either standalone (preview) or as a userscript.

## Why not pure Python?

A userscript runs in the page's JS runtime to hook Phaser, read game state, draw
with WebGL, play audio, and capture input. None of that is reachable from
Python. What *is* portable &mdash; and faithfully ported here &mdash; is the
deterministic logic: the **Alea** PRNG (identical to the JS `random-seed`
package), the `config.js` tuning constants, and the track-generation math.

## Install

```bash
cd nt-track-py
python -m pip install -e .          # optional; or just run from this directory
python -m pip install -e ".[dev]"   # with pytest
```

No third-party runtime dependencies. Requires Python 3.10+.

## Usage

Emit the layout JSON:

```bash
python -m ntrack generate --seed NEON --lanes 4 --out track.json
```

Build the browser artifacts (userscript + standalone preview + JSON):

```bash
python -m ntrack build --seed NEON --lanes 4 --outdir dist
```

Outputs in `dist/`:

- `preview-2d.html` &mdash; top-down **2D track map**: the segment curvature is
  integrated into a closed circuit and drawn with lane markings, scenery and
  animated cars. Open it directly in a browser.
- `preview.html` &mdash; pseudo-3D road preview of the same layout. No Nitro Type
  account or network needed.
- `nt-track.user.js` &mdash; install in Tampermonkey/Greasemonkey for the Nitro Type
  overlay. The live-site adapter is stubbed (see *Limitations*).
- `track.json` &mdash; the raw layout.

### Car animation preview

Build a standalone page that animates a single Nitro Type car the way the game
does (composited with nt-animator, rendered with PIXI, steered by the mouse):

```bash
python -m ntrack car 372 --outdir dist
```

`372` is a Nitro Type car id; an asset key such as `wflower` works too. Outputs
in `dist/`:

- `car-preview.html` &mdash; the car page; composition, spritesheet frames and the
  spritesheet image are inlined, so only `nt-animator.js` sits next to it.

Every animated car in one page, with a picker (and `cars.html#<asset key>` to
open on a specific car):

```bash
python -m ntrack cars --outdir dist
```

- `cars.html` &mdash; ~10 MB self-contained gallery of all 114 animated cars
- `nt-animator.js` &mdash; vendored browser bundle of
  [teachingcom/nt-animator](https://github.com/teachingcom/nt-animator)

The animation data (compositions, spritesheet frames, car id map, spritesheets)
is vendored in `ntrack/vendor/`, so both pages work offline.

### CLI options

```
--seed TEXT     deterministic seed (same seed -> same track)
--lanes N       number of lanes (1-8, default 4)
--length FLOAT  track length in world units (default 175)
--cars N        number of cars (default 6)
--segments N    number of road segments (default 40)
```

## Deterministic seeds

`ntrack.rng` is a faithful port of the **Alea 0.9** PRNG used by the `random-seed`
npm package. The same seed produces the same sequence in Python and in the
browser, so the Python-generated layout matches what the JS side computes for
that seed.

```python
from ntrack import generate_track
layout = generate_track(seed="NEON")
print(layout.name, layout.lane_count, len(layout.cars))
```

## Project layout

```
ntrack/
  rng.py         Alea PRNG + Random helpers (port of src/rng.js)
  config.py      tuning constants (port of src/config.js)
  track.py       deterministic TrackLayout generator
  userscript.py  JS renderers (pseudo-3D + top-down 2D) and HTML/userscript builders
  carpreview.py  standalone nt-animator car preview + all-cars gallery builders
  vendor/        nt-animator bundle, car manifest, id/name maps, 114 spritesheets
  cli.py         `generate` / `build` / `car` / `cars` commands
tests/           pytest suite
```

## Car animations (nt-animator)

`ntrack/vendor/nt-animator.js` is the published browser bundle of
[nt-animator](https://github.com/teachingcom/nt-animator) (GPL-3.0-or-later, same
license as this project). Two things use it:

**`car-preview.html` / `cars.html` (the car itself).** `ntrack car 372` composes
the car from the vendored manifest &mdash; body, shadow, wheels and any particle
emitters &mdash; and renders it with PIXI. The spritesheet is sliced into textures at
load time and handed to nt-animator pre-initialised, so nothing is fetched.
Moving the mouse feeds the stage pointer values the composition reads, which is
what makes the car lean and the wheels spin. `ntrack cars` builds the same thing
for all 114 animated cars with a picker; switching disposes the old car and its
textures.

**`preview-2d.html` (track cars).** Each car is a PIXI sprite whose texture is
drawn procedurally in the car colour, and its pace is an `animate()` tween
(keyframes, `easeInOutSine`, `alternate` looping) so cars surge and fall back
instead of sliding at constant speed. Without the bundle it falls back to plain
rectangles.

nt-animator ships as a Parcel CommonJS bundle, so the pages define `window.module`
plus a small `require("url")` shim before including it, and pick the exports up
from `module.exports`.

## Limitations / what is *not* ported

- **The Phaser renderer.** The original `src/views/**` renders with WebGL inside
  the Nitro Type page. Here it is replaced with a dependency-free pseudo-3D canvas
  renderer good enough to preview a layout.
- **Live-site adapter.** `window.NTTRACK` exposes `findGame`, `onRaceStart`,
  `destroy` as no-op stubs. Wiring these requires the Nitro Type game internals
  (game instance, scene graph, car/texture loading), which are not public.
- **Car / paint data.** The original fetches real cars from the Nitro Type API;
  the track preview uses a deterministic placeholder palette. The car pages use
  the real animation data mirrored by the Nitro Type data archive: 114 cars have
  published animation (compositions + spritesheets), the rest do not.

## License

Upstream `nt-track` is GPL-3.0. This port is released under **GPL-3.0-or-later**
to stay compatible.