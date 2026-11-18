"""nt-track-py: Python track generator + browser renderer for Nitro Type.

A hybrid reimplementation of teachingcom/nt-track. The deterministic layout
logic (seeded RNG, config constants, track generation) lives in Python; the
browser rendering layer stays in JavaScript because Python cannot run inside a
web page. See :mod:`ntrack.userscript` for the JS half.
"""

from . import config
from .rng import Random, Uheprng
from .track import Car, Scenery, Segment, TrackLayout, generate_track
from .userscript import build_preview_html, build_userscript

__all__ = [
    "config",
    "Random",
    "Uheprng",
    "Car",
    "Scenery",
    "Segment",
    "TrackLayout",
    "generate_track",
    "build_preview_html",
    "build_userscript",
]

__version__ = config.NTTRACK_VERSION