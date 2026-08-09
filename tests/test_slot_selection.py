"""The polling URL's slot arithmetic.

`src/settings.yml` selects a card with

    {{ "now" | date: "%s" | divided_by: SECONDS | modulo: COUNT }}

which is: seconds since the Unix epoch, integer-divided by the slot length,
modulo the number of slot files. This module reproduces that in Python and
pins the properties the design depends on.

The URL deliberately uses UTC and carries no date. An earlier design used the
device's local date, which needed care around daylight saving; a slot index
derived from the epoch is immune to time zones altogether, and because there
is no date in the path the API can never run out of coverage.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUILD = yaml.safe_load((REPO / "config" / "build.yml").read_text(encoding="utf-8"))
SECONDS = BUILD["slots"]["seconds"]
COUNT = BUILD["slots"]["count"]


def slot(moment: datetime) -> int:
    """Exactly what the Liquid expression computes."""
    return (int(moment.timestamp()) // SECONDS) % COUNT


def test_the_slot_is_stable_within_its_window():
    """A refresh inside one slot must redraw the same card, not flicker."""
    base = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    assert slot(base) == slot(base + timedelta(seconds=SECONDS - 1))


def test_the_slot_advances_at_the_boundary():
    base = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    assert slot(base) != slot(base + timedelta(seconds=SECONDS))


def test_consecutive_renders_always_change_the_card():
    """TRMNL renders at most every 15 minutes; the slot must be shorter.

    If a slot outlasted the render interval, two renders could land in the
    same slot, the payload would be byte-identical, and TRMNL would skip the
    render — the screen would appear frozen. That is the exact failure this
    whole design exists to avoid.
    """
    render_interval = 15 * 60
    assert SECONDS <= render_interval
    base = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    for step in range(20):
        a = base + timedelta(seconds=step * render_interval)
        b = a + timedelta(seconds=render_interval)
        assert slot(a) != slot(b), f"repeat at step {step}"


def test_the_slot_index_is_always_in_range():
    """Out of range means requesting a file that was never generated."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for hours in range(0, 24 * 40, 7):
        assert 0 <= slot(base + timedelta(hours=hours)) < COUNT


def test_the_cycle_length_is_what_the_config_claims():
    days = COUNT * SECONDS / 86400
    assert days > 14, "a cycle shorter than a fortnight would feel repetitive"
    base = datetime(2026, 8, 9, tzinfo=timezone.utc)
    assert slot(base) == slot(base + timedelta(seconds=COUNT * SECONDS))


@pytest.mark.parametrize(
    "zone", ["Europe/London", "Asia/Tokyo", "America/New_York", "Asia/Kathmandu"]
)
def test_the_slot_does_not_depend_on_time_zone(zone):
    """The same instant gives the same slot wherever the device thinks it is."""
    moment = datetime(2026, 8, 9, 12, 34, tzinfo=timezone.utc)
    assert slot(moment) == slot(moment.astimezone(ZoneInfo(zone)))


def test_daylight_saving_does_not_disturb_the_sequence():
    """The UK transitions are a non-event for an epoch-derived index."""
    for transition in (
        datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc),
    ):
        before = slot(transition - timedelta(seconds=SECONDS))
        at = slot(transition)
        after = slot(transition + timedelta(seconds=SECONDS))
        assert before != at != after
        assert (at - before) % COUNT == 1
        assert (after - at) % COUNT == 1
