"""Deterministic daily word selection.

Requirements this module exists to satisfy:

* the same level and date always resolve to the same word;
* every word at a level appears exactly once per complete cycle;
* no word repeats inside a cycle, and none repeats across a cycle boundary;
* results are stable across Python releases and across processes.

The last point rules out :mod:`random`, :func:`hash` and any library shuffle
whose algorithm is an implementation detail. Instead we derive a 64-bit seed
with SHA-256 and drive an explicit SplitMix64 generator through an explicit
Fisher-Yates shuffle, both written out in full below.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

MASK64 = 0xFFFFFFFFFFFFFFFF
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15


class SplitMix64:
    """The SplitMix64 generator, written out so it can never drift.

    Reference: Steele, Lea & Flood, "Fast splittable pseudorandom number
    generators" (OOPSLA 2014). Chosen because it is tiny, well distributed and
    trivially reproducible in any language, which matters if this schedule
    ever has to be recomputed outside Python.
    """

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & MASK64

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN_GAMMA) & MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return (z ^ (z >> 31)) & MASK64

    def below(self, bound: int) -> int:
        """Uniform integer in ``[0, bound)`` using rejection sampling.

        Rejection sampling rather than a modulo keeps the distribution exactly
        uniform, which matters because a biased shuffle would quietly favour
        some words over others across cycles.
        """
        if bound <= 0:
            raise ValueError("bound must be positive")
        if bound & (bound - 1) == 0:  # power of two
            return self.next_u64() & (bound - 1)
        limit = MASK64 - (MASK64 % bound)
        while True:
            value = self.next_u64()
            if value <= limit:
                return value % bound


def derive_seed(
    selection_version: str, level: str, cycle: int, selection_salt: str = ""
) -> int:
    """Derive the 64-bit shuffle seed for one level's cycle."""
    payload = "\0".join([selection_version, level, str(cycle), selection_salt])
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def shuffled(
    items: Sequence[str],
    selection_version: str,
    level: str,
    cycle: int,
    selection_salt: str = "",
) -> list[str]:
    """Return a deterministic permutation of *items* for one cycle.

    Fisher-Yates, written out explicitly and walking downwards, so the result
    depends only on the seed and the input order.
    """
    result = list(items)
    seed = derive_seed(selection_version, level, cycle, selection_salt)
    rng = SplitMix64(seed)
    for i in range(len(result) - 1, 0, -1):
        j = rng.below(i + 1)
        result[i], result[j] = result[j], result[i]
    return result


@dataclass(frozen=True)
class Selection:
    """The scheduling result for one level on one date."""

    entry_id: str
    cycle: int
    position: int  # one-based position within the cycle
    total: int


class Scheduler:
    """Resolves (level, date) to a word, caching one permutation per cycle.

    A site build walks thousands of consecutive dates, which span only a
    handful of cycles, so permutations are memoised rather than recomputed per
    date.

    Boundary-repeat avoidance
    -------------------------
    A naive "rotate the next cycle if it starts with the previous cycle's last
    word" rule is recursive: the previous cycle's *last* word depends on
    whether that cycle was itself rotated, and so on backwards forever. Instead
    the fix here swaps only the first two positions, which for three or more
    words leaves the final position untouched. The last word of a cycle is
    therefore always the raw shuffle's last word, the rule depends on nothing
    but the two adjacent raw shuffles, and the guarantee is exact:
    ``permutation[1]`` cannot equal the previous last word because
    ``permutation[0]`` already does and identifiers are unique.

    Two special cases:

    * ``N == 1`` — one word repeats every day by definition; nothing to avoid.
    * ``N == 2`` — swapping the front would also move the final position, so
      the two-word case is scheduled as a fixed alternation instead, which
      never repeats.
    """

    def __init__(
        self,
        ordered_ids: Sequence[str],
        level: str,
        epoch_date: date,
        selection_version: str = "1",
        selection_salt: str = "",
    ) -> None:
        if not ordered_ids:
            raise ValueError(f"no active entries for level {level!r}")
        self.ordered_ids = list(ordered_ids)
        self.level = level
        self.epoch_date = epoch_date
        self.selection_version = selection_version
        self.selection_salt = selection_salt
        self._raw_cache: dict[int, list[str]] = {}
        self._cache: dict[int, list[str]] = {}

    @property
    def total(self) -> int:
        return len(self.ordered_ids)

    def _raw(self, cycle: int) -> list[str]:
        if cycle not in self._raw_cache:
            self._raw_cache[cycle] = shuffled(
                self.ordered_ids,
                self.selection_version,
                self.level,
                cycle,
                self.selection_salt,
            )
        return self._raw_cache[cycle]

    def permutation(self, cycle: int) -> list[str]:
        """The final, boundary-corrected permutation for *cycle*."""
        if cycle in self._cache:
            return self._cache[cycle]

        total = self.total
        if total == 1:
            result = list(self.ordered_ids)
        elif total == 2:
            # With two words, the only infinite sequence free of adjacent
            # repeats is a strict alternation, so every cycle uses the same
            # order: a, b | a, b, ... The schedule is fully predictable at
            # this size, which is unavoidable rather than a defect.
            result = list(self.ordered_ids)
        else:
            result = list(self._raw(cycle))
            if result[0] == self._raw(cycle - 1)[-1]:
                result[0], result[1] = result[1], result[0]

        self._cache[cycle] = result
        return result

    def at_position(self, position: int) -> Selection:
        """The word at absolute *position* in the endless shuffled stream.

        Think of the shuffled cycles laid end to end: position 0 is the first
        word of cycle 0, position N the first word of cycle 1, and negative
        positions run backwards. Python's floor division makes that work
        without a special case.
        """
        cycle, offset = divmod(position, self.total)
        return Selection(
            entry_id=self.permutation(cycle)[offset],
            cycle=cycle,
            position=offset + 1,
            total=self.total,
        )

    def select(self, requested_date: date) -> Selection:
        """Choose the single word for *requested_date*."""
        return self.at_position((requested_date - self.epoch_date).days)


def select(
    ordered_ids: Sequence[str],
    level: str,
    requested_date: date,
    epoch_date: date,
    selection_version: str = "1",
    selection_salt: str = "",
) -> Selection:
    """One-shot convenience wrapper around :class:`Scheduler`.

    *ordered_ids* must already be stable-sorted by ID; the caller owns that
    ordering because it is also what the validation layer checks.
    """
    return Scheduler(
        ordered_ids, level, epoch_date, selection_version, selection_salt
    ).select(requested_date)
