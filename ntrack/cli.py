"""Command line interface for nt-track-py.

Usage::

    python -m ntrack generate --seed NEON --lanes 4 --out track.json
    python -m ntrack build    --seed NEON --outdir dist
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import config
from .carpreview import (
    CarDataError,
    build_car_gallery_html,
    build_car_preview_html,
    resolve_car,
)
from .track import generate_track
from .userscript import (
    ANIMATOR_BUNDLE,
    build_2d_preview_html,
    build_preview_html,
    build_userscript,
)


def _cmd_generate(args: argparse.Namespace) -> int:
    layout = generate_track(
        seed=args.seed,
        lane_count=args.lanes,
        length=args.length,
        car_count=args.cars,
        segment_count=args.segments,
    )
    data = json.dumps(layout.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(data, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        sys.stdout.write(data + "\n")
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    layout = generate_track(
        seed=args.seed,
        lane_count=args.lanes,
        length=args.length,
        car_count=args.cars,
        segment_count=args.segments,
    )
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    userscript = outdir / "nt-track.user.js"
    preview = outdir / "preview.html"
    preview_2d = outdir / "preview-2d.html"
    json_path = outdir / "track.json"

    userscript.write_text(build_userscript(layout), encoding="utf-8")
    preview.write_text(build_preview_html(layout), encoding="utf-8")
    preview_2d.write_text(build_2d_preview_html(layout), encoding="utf-8")
    json_path.write_text(json.dumps(layout.to_dict(), indent=2), encoding="utf-8")

    animator = _copy_animator(outdir)

    print(f"track:  {layout.name}  (seed={layout.seed}, lanes={layout.lane_count}, cars={len(layout.cars)})")
    print(f"wrote {userscript}")
    print(f"wrote {preview}")
    print(f"wrote {preview_2d}")
    print(f"wrote {json_path}")
    if animator is not None:
        print(f"wrote {animator}")
    print(f"\nOpen {preview_2d.resolve()} for the 2D track map.")
    print(f"Open {preview.resolve()} for the pseudo-3D preview.")
    print(f"Install {userscript.name} in Tampermonkey for the Nitro Type overlay.")
    return 0


def _copy_animator(outdir: Path) -> Path | None:
    """Copy the vendored nt-animator bundle next to the generated pages."""
    if not ANIMATOR_BUNDLE.exists():
        print(f"warning: {ANIMATOR_BUNDLE} missing, previews will use plain car rectangles")
        return None
    target = outdir / ANIMATOR_BUNDLE.name
    target.write_bytes(ANIMATOR_BUNDLE.read_bytes())
    return target


def _cmd_car(args: argparse.Namespace) -> int:
    try:
        asset_key, car_id = resolve_car(args.car)
        html = build_car_preview_html(asset_key)
    except CarDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    page = outdir / args.name
    page.write_text(html, encoding="utf-8")

    print(f"car:    {car_id or '-'}  ({asset_key})")
    print(f"wrote {page}")
    if _copy_animator(outdir) is not None:
        print(f"wrote {outdir / ANIMATOR_BUNDLE.name}")
    print(f"\nOpen {page.resolve()} and move the mouse over the car.")
    return 0


def _cmd_cars(args: argparse.Namespace) -> int:
    try:
        html = build_car_gallery_html()
    except CarDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    page = outdir / args.name
    page.write_text(html, encoding="utf-8")

    total = len(re.findall(r'"png":"data:image/png;base64,', html))
    print(f"cars:   {total} animated cars")
    print(f"wrote {page}  ({page.stat().st_size / 1024 / 1024:.1f} MB)")
    if _copy_animator(outdir) is not None:
        print(f"wrote {outdir / ANIMATOR_BUNDLE.name}")
    print(f"\nOpen {page.resolve()} and pick a car (or use {page.stem}.html#<asset key>).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ntrack",
        description="Python track generator + browser renderer for Nitro Type (nt-track-py).",
    )
    parser.add_argument("--version", action="version", version=f"nt-track-py {config.NTTRACK_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--seed", default=None, help="deterministic seed (string)")
        p.add_argument("--lanes", type=int, default=4, help="number of lanes (1-8)")
        p.add_argument("--length", type=float, default=None, help="track length in world units")
        p.add_argument("--cars", type=int, default=6, help="number of cars")
        p.add_argument("--segments", type=int, default=40, help="number of road segments")

    gen = sub.add_parser("generate", help="emit track layout JSON to stdout or a file")
    add_common(gen)
    gen.add_argument("--out", default=None, help="write JSON to this path instead of stdout")
    gen.set_defaults(func=_cmd_generate)

    build = sub.add_parser("build", help="emit userscript + preview HTML + JSON")
    add_common(build)
    build.add_argument("--outdir", default="dist", help="output directory (default: dist)")
    build.set_defaults(func=_cmd_build)

    car = sub.add_parser(
        "car",
        help="emit a hover-animated car page (nt-animator + PIXI)",
    )
    car.add_argument(
        "car",
        nargs="?",
        default="372",
        help="Nitro Type car id (e.g. 372) or asset key (e.g. wflower)",
    )
    car.add_argument("--outdir", default="dist", help="output directory (default: dist)")
    car.add_argument("--name", default="car-preview.html", help="output file name")
    car.set_defaults(func=_cmd_car)

    cars = sub.add_parser(
        "cars",
        help="emit a gallery page with every animated car",
    )
    cars.add_argument("--outdir", default="dist", help="output directory (default: dist)")
    cars.add_argument("--name", default="cars.html", help="output file name")
    cars.set_defaults(func=_cmd_cars)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())