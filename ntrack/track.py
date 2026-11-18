"""Deterministic track-layout generation.

This is the portable *logic* half of ``nt-track``. The upstream ``Track`` view is
a Phaser scene that both computes a layout and renders it with WebGL; here we keep
only the computation and emit a plain, JSON-serialisable description of the
result. The JavaScript layer (:mod:`ntrack.userscript`) renders that description
in the browser.

Because generation is seeded through :class:`ntrack.rng.Random` (an exact Alea
port), the same seed always yields the same layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Optional

from . import config
from .rng import Random

# A small palette used to tint generated cars. Upstream pulls real car paint
# jobs from the Nitro Type API; this is a deterministic stand-in so the preview
# works offline.
_CAR_COLORS = [
    "#e53935", "#1e88e5", "#43a047", "#fdd835", "#8e24aa",
    "#fb8c00", "#00acc1", "#6d4c41", "#546e7a", "#d81b60",
]

_TRACK_NAME_A = ["Neon", "Sunset", "Turbo", "Midnight", "Canyon", "Pixel", "Chrome", "Velocity"]
_TRACK_NAME_B = ["Run", "Sprint", "Circuit", "Dash", "Highway", "Loop", "Rally", "Speedway"]


@dataclass
class Segment:
    """One piece of road between two scenery anchors."""

    index: int
    kind: str          # "straight" | "curve"
    length: float      # world units
    curve: float       # -1..1, 0 for straights

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Scenery:
    """A crowd stand / billboard placed alongside the track."""

    id: int
    segment: int
    side: str          # "left" | "right"
    variation: int     # crowd animation variation
    distance: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Car:
    """A racer placed on the grid."""

    id: str
    name: str
    color: str
    lane: int
    distance: float
    is_player: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrackLayout:
    """Complete, serialisable description of a generated track."""

    seed: str
    name: str
    lane_count: int
    length: float
    scroll_speed: float
    segments: List[Segment] = field(default_factory=list)
    scenery: List[Scenery] = field(default_factory=list)
    cars: List[Car] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "name": self.name,
            "lane_count": self.lane_count,
            "length": self.length,
            "scroll_speed": self.scroll_speed,
            "segments": [s.to_dict() for s in self.segments],
            "scenery": [s.to_dict() for s in self.scenery],
            "cars": [c.to_dict() for c in self.cars],
        }


def _make_name(rnd: Random) -> str:
    return f"{rnd.select(_TRACK_NAME_A)} {rnd.select(_TRACK_NAME_B)}"


def generate_track(
    seed: Optional[str] = None,
    lane_count: int = 4,
    length: Optional[float] = None,
    car_count: int = 6,
    segment_count: int = 40,
) -> TrackLayout:
    """Build a deterministic :class:`TrackLayout`.

    Parameters
    ----------
    seed:
        Any string (or ``None`` for a time-based seed).
    lane_count:
        Number of racing lanes (1..8).
    length:
        Total track length in world units. Defaults to
        :data:`ntrack.config.TRACK_MAXIMUM_TRAVEL_DISTANCE`.
    car_count:
        How many cars to place on the grid.
    segment_count:
        Number of road segments the length is split into.
    """

    lane_count = max(1, min(8, lane_count))
    segment_count = max(1, segment_count)
    if length is None:
        length = float(config.TRACK_MAXIMUM_TRAVEL_DISTANCE)
    length = float(length)

    rnd = Random(seed)
    resolved_seed = seed if seed not in (None, "") else "generated"

    track = TrackLayout(
        seed=str(resolved_seed),
        name=_make_name(rnd),
        lane_count=lane_count,
        length=length,
        scroll_speed=float(config.TRACK_MAXIMUM_SCROLL_SPEED),
    )

    # --- road segments ---------------------------------------------------
    base = length / segment_count
    for i in range(segment_count):
        if rnd.random() < 0.55:
            kind = "curve"
            curve = rnd.float(-1.0, 1.0)
            if abs(curve) < 0.08:
                curve = 0.08 if curve >= 0 else -0.08
            seg_len = base * rnd.float(0.8, 1.3)
        else:
            kind = "straight"
            curve = 0.0
            seg_len = base * rnd.float(0.9, 1.1)
        track.segments.append(Segment(index=i, kind=kind, length=round(seg_len, 4), curve=round(curve, 4)))

    # --- crowd / billboard scenery --------------------------------------
    scenery_id = 0
    for seg in track.segments:
        for side in ("left", "right"):
            if rnd.random() < 0.35:
                track.scenery.append(
                    Scenery(
                        id=scenery_id,
                        segment=seg.index,
                        side=side,
                        variation=rnd.int(config.CROWD_ANIMATION_VARIATIONS - 1),
                        distance=round(base * seg.index + rnd.float(0.0, base), 4),
                    )
                )
                scenery_id += 1

    # --- cars on the grid ------------------------------------------------
    car_count = max(1, min(car_count, lane_count * 2))
    palette = list(_CAR_COLORS)
    for i in range(car_count):
        lane = i % lane_count
        row = i // lane_count
        distance = round(config.TRACK_STARTING_LINE_POSITION * length * 0.01 + row * 0.8, 4)
        color = palette[i % len(palette)]
        is_player = i == 0
        track.cars.append(
            Car(
                id=f"car_{i}",
                name=("You" if is_player else f"Racer {i}"),
                color=color,
                lane=lane,
                distance=distance,
                is_player=is_player,
            )
        )

    return track