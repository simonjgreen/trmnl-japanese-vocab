"""Determinism and rotation guarantees for the daily schedule."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta

import pytest

from kotoba.selection import Scheduler, SplitMix64, derive_seed, select, shuffled

EPOCH = date(2026, 1, 1)


def ids(n: int) -> list[str]:
    return [f"demo:{i:04d}" for i in range(n)]


def sequence(scheduler: Scheduler, start_offset: int, days: int) -> list[str]:
    return [
        scheduler.select(EPOCH + timedelta(days=start_offset + d)).entry_id
        for d in range(days)
    ]


class TestSplitMix64:
    def test_is_deterministic(self):
        a = SplitMix64(12345)
        b = SplitMix64(12345)
        assert [a.next_u64() for _ in range(5)] == [b.next_u64() for _ in range(5)]

    def test_stays_inside_64_bits(self):
        rng = SplitMix64(1)
        assert all(0 <= rng.next_u64() <= 0xFFFFFFFFFFFFFFFF for _ in range(200))

    def test_below_respects_the_bound(self):
        rng = SplitMix64(7)
        assert all(0 <= rng.below(10) < 10 for _ in range(500))

    def test_below_rejects_a_non_positive_bound(self):
        with pytest.raises(ValueError):
            SplitMix64(1).below(0)

    def test_below_is_reasonably_uniform(self):
        rng = SplitMix64(99)
        counts = [0] * 6
        for _ in range(60_000):
            counts[rng.below(6)] += 1
        assert all(9_000 < c < 11_000 for c in counts), counts


class TestShuffle:
    def test_is_a_permutation(self):
        items = ids(50)
        assert sorted(shuffled(items, "1", "n3", 0)) == sorted(items)

    def test_does_not_mutate_its_input(self):
        items = ids(10)
        original = list(items)
        shuffled(items, "1", "n3", 0)
        assert items == original

    def test_seed_depends_on_every_component(self):
        base = derive_seed("1", "n3", 0, "salt")
        assert derive_seed("2", "n3", 0, "salt") != base
        assert derive_seed("1", "n2", 0, "salt") != base
        assert derive_seed("1", "n3", 1, "salt") != base
        assert derive_seed("1", "n3", 0, "other") != base


class TestSelection:
    def test_same_level_and_date_give_the_same_word(self):
        a = select(ids(30), "n3", date(2026, 8, 9), EPOCH)
        b = select(ids(30), "n3", date(2026, 8, 9), EPOCH)
        assert a == b

    def test_different_days_advance_the_position(self):
        scheduler = Scheduler(ids(30), "n3", EPOCH)
        first = scheduler.select(EPOCH)
        second = scheduler.select(EPOCH + timedelta(days=1))
        assert second.position == first.position + 1
        assert second.entry_id != first.entry_id

    @pytest.mark.parametrize("n", [3, 4, 7, 30, 101])
    def test_every_word_appears_exactly_once_per_cycle(self, n):
        scheduler = Scheduler(ids(n), "n3", EPOCH)
        for cycle in range(-2, 4):
            window = sequence(scheduler, cycle * n, n)
            assert sorted(window) == sorted(ids(n)), f"cycle {cycle}"

    @pytest.mark.parametrize("n", [2, 3, 4, 7, 30, 101])
    def test_no_word_repeats_on_consecutive_days(self, n):
        scheduler = Scheduler(ids(n), "n3", EPOCH)
        seq = sequence(scheduler, -3 * n, 8 * n)
        repeats = [a for a, b in zip(seq, seq[1:]) if a == b]
        assert repeats == []

    def test_single_entry_level_repeats_by_definition(self):
        # With one word there is nothing to alternate with; this is documented
        # behaviour rather than a bug.
        scheduler = Scheduler(["demo:only"], "n1", EPOCH)
        assert sequence(scheduler, 0, 3) == ["demo:only"] * 3

    def test_two_entry_level_strictly_alternates(self):
        scheduler = Scheduler(["a", "b"], "n1", EPOCH)
        seq = sequence(scheduler, 0, 6)
        assert all(x != y for x, y in zip(seq, seq[1:]))

    def test_dates_before_the_epoch_are_defined(self):
        scheduler = Scheduler(ids(10), "n3", EPOCH)
        result = scheduler.select(EPOCH - timedelta(days=1))
        assert result.cycle == -1
        assert result.position == 10
        assert result.entry_id in ids(10)

    def test_levels_have_independent_schedules(self):
        items = ids(40)
        per_level = {
            level: [
                select(items, level, EPOCH + timedelta(days=d), EPOCH).entry_id
                for d in range(15)
            ]
            for level in ("n5", "n4", "n3", "n2", "n1")
        }
        distinct = {tuple(v) for v in per_level.values()}
        assert len(distinct) == 5

    def test_empty_level_is_rejected(self):
        with pytest.raises(ValueError):
            Scheduler([], "n3", EPOCH)

    def test_sequence_metadata_is_consistent(self):
        scheduler = Scheduler(ids(12), "n3", EPOCH)
        result = scheduler.select(EPOCH + timedelta(days=13))
        assert result.total == 12
        assert result.cycle == 1
        assert result.position == 2

    def test_changing_selection_version_changes_the_schedule(self):
        items = ids(20)
        a = select(items, "n3", EPOCH, EPOCH, selection_version="1")
        b = select(items, "n3", EPOCH, EPOCH, selection_version="2")
        assert a.entry_id != b.entry_id


def test_result_is_stable_across_separate_processes():
    """Guards against hash randomisation or any process-global RNG creeping in."""
    code = (
        "from datetime import date;"
        "from kotoba.selection import select;"
        "print(select([f'demo:{i:04d}' for i in range(200)], 'n3',"
        " date(2026, 8, 9), date(2026, 1, 1), '1', 'kotoba').entry_id)"
    )
    outputs = set()
    for seed in ("0", "1", "random"):
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        )
        outputs.add(result.stdout.strip())
    assert len(outputs) == 1, outputs
