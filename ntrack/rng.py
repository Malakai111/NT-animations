"""Seeded pseudo-random number generation.

The upstream project (``nt-track``) seeds every random decision with the
``random-seed`` npm package. That package is **UHEPRNG** (Ultra High Entropy
PRNG) by Steve Gibson / Gibson Research Corporation, a Multiply-With-Carry
generator with a 48-word state array, seeded through a Mash hash.

This module is a faithful Python port of that algorithm, so a given seed produces
the exact same sequence in Python as it does in the browser (via ``random-seed``).
That is what lets the Python-generated layout match the JavaScript renderer.

JavaScript's ``>>> 0`` (ToUint32) and ``| 0`` (ToInt32) coercions are reproduced
by :func:`_to_uint32` and :func:`_to_int32`.
"""

from __future__ import annotations

import json
import math
import random as _pyrandom
import re
import time

_U32 = 0xFFFFFFFF
_MAX_VALUE = 1.7976931348623157e308  # Number.MAX_VALUE
_ORDER = 48


def _to_uint32(value: float) -> int:
    """Equivalent of JavaScript's ``value >>> 0`` (ToUint32)."""
    return int(value) & _U32


def _to_int32(value: float) -> int:
    """Equivalent of JavaScript's ``value | 0`` (ToInt32)."""
    n = int(value) & _U32
    return n - 0x100000000 if n >= 0x80000000 else n


def _mash_factory():
    """Return a stateful ``mash`` function matching UHEPRNG's Mash()."""
    state = {"n": 0xEFC8249D}

    def mash(data=None):
        if data:  # JS: if (data) -- falsy values reset the hash state
            text = data if isinstance(data, str) else str(data)
            n = state["n"]
            for ch in text:
                n = n + ord(ch)
                h = 0.02519603282416938 * n
                n = _to_uint32(h)
                h -= n
                h *= n
                n = _to_uint32(h)
                h -= n
                # intentionally *not* masked: JS keeps this as a float > 2**32
                n = n + h * 0x100000000
            state["n"] = n
            return _to_uint32(n) * 2.3283064365386963e-10
        state["n"] = 0xEFC8249D
        return None

    return mash


def _clean_string(text: str) -> str:
    """Port of ``random.cleanString``."""
    text = text.strip()
    text = re.sub(r"[\x00-\x1F]", "", text)
    text = text.replace("\n ", "\n", 1)
    return text


def _stringify(seed) -> str:
    """Port of the JSON stringify step in ``random.seed`` for non-strings."""
    try:
        return json.dumps(seed, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(seed)


class Uheprng:
    """UHEPRNG (Steve Gibson / GRC), as wrapped by the ``random-seed`` package.

    Call :meth:`random` for floats in ``[0, 1)``, :meth:`int_between` for
    inclusive integers, and :meth:`float_between` for ``[min, max)`` floats --
    matching ``random-seed``'s semantics.
    """

    def __init__(self, seed=None):
        self._s = [0.0] * _ORDER
        self._c = 1
        self._p = _ORDER
        self._mash = _mash_factory()
        # The upstream constructor seeds from Math.random(); overwritten by seed().
        for i in range(_ORDER):
            self._s[i] = self._mash(_pyrandom.random())
        if seed is not None:
            self.seed(seed)

    # -- seeding ---------------------------------------------------------
    def _init_state(self) -> None:
        self._mash(None)  # reset the mash hash
        for i in range(_ORDER):
            self._s[i] = self._mash(" ")
        self._c = 1
        self._p = _ORDER

    def _hash_string(self, text: str) -> None:
        text = _clean_string(text)
        self._mash(text)
        for i in range(len(text)):
            k = ord(text[i])
            for j in range(_ORDER):
                self._s[j] -= self._mash(k)
                if self._s[j] < 0:
                    self._s[j] += 1

    def seed(self, seed=None) -> None:
        if seed is None:
            seed = _pyrandom.random()
        if not isinstance(seed, str):
            seed = _stringify(seed)
        self._init_state()
        self._hash_string(seed)

    # -- generation ------------------------------------------------------
    def _rawprng(self) -> float:
        self._p += 1
        if self._p >= _ORDER:
            self._p = 0
        t = 1768863 * self._s[self._p] + self._c * 2.3283064365386963e-10
        self._c = _to_int32(t)
        self._s[self._p] = t - self._c
        return self._s[self._p]

    def _random(self, rng_range: float) -> int:
        return math.floor(
            rng_range
            * (self._rawprng() + _to_int32(self._rawprng() * 0x200000) * 1.1102230246251565e-16)
        )

    def random(self) -> float:
        return self._random(_MAX_VALUE - 1) / _MAX_VALUE

    def float_between(self, minimum: float, maximum: float) -> float:
        return self.random() * (maximum - minimum) + minimum

    def int_between(self, minimum: int, maximum: int) -> int:
        if maximum < minimum:
            minimum, maximum = maximum, minimum
        return math.floor(self.random() * (maximum - minimum + 1)) + minimum


class Random:
    """Python port of ``src/rng.js`` (the ``Random`` convenience wrapper)."""

    def __init__(self, seed=None):
        if seed is None or seed == "":
            seed = str(int(time.time() * 1000))
        self._rng = Uheprng(seed)

    def int(self, a: int, b: int | None = None) -> int:
        return self._rng.int_between(0, a) if b is None else self._rng.int_between(a, b)

    def float(self, a: float, b: float | None = None) -> float:
        return self._rng.float_between(0, a) if b is None else self._rng.float_between(a, b)

    def random(self) -> float:
        return self._rng.random()

    def select(self, source):
        return source[int(self.random() * len(source))]