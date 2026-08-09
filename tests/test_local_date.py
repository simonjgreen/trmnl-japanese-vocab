"""The polling URL must resolve to the device's local date, not UTC.

`src/settings.yml` builds the URL with

    {{ "now" | date: "%s" | plus: trmnl.user.utc_offset | date: "%Y-%m-%d" }}

which is: take the server clock as a UTC epoch, add the device's *current*
UTC offset in seconds, then format the date. This module reproduces that
arithmetic in Python and checks it against a real timezone database, with
particular attention to the UK's daylight-saving transitions — the account
this was built for is set to Europe/London, where getting this wrong shows
the previous day's word for an hour every night through the summer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

LONDON = ZoneInfo("Europe/London")

# The two 2026 UK transitions.
BST_STARTS = datetime(2026, 3, 29, 1, 0, tzinfo=timezone.utc)   # +0 -> +1
BST_ENDS = datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc)    # +1 -> +0


def polling_date(now_utc: datetime, utc_offset_seconds: int) -> str:
    """Exactly what the Liquid expression computes."""
    epoch = int(now_utc.timestamp())
    shifted = epoch + utc_offset_seconds
    return datetime.fromtimestamp(shifted, tz=timezone.utc).strftime("%Y-%m-%d")


def actual_local_date(now_utc: datetime, zone: ZoneInfo = LONDON) -> str:
    """The date a person in *zone* would say it is."""
    return now_utc.astimezone(zone).strftime("%Y-%m-%d")


def offset_for(now_utc: datetime, zone: ZoneInfo = LONDON) -> int:
    """What TRMNL reports as trmnl.user.utc_offset at that moment."""
    return int(now_utc.astimezone(zone).utcoffset().total_seconds())


@pytest.mark.parametrize(
    "moment",
    [
        # Deep in GMT.
        datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc),
        datetime(2026, 1, 16, 0, 30, tzinfo=timezone.utc),
        # Deep in BST — 23:30 UTC is already tomorrow locally.
        datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc),
        datetime(2026, 7, 16, 0, 30, tzinfo=timezone.utc),
        # Either side of the spring forward.
        BST_STARTS - timedelta(minutes=30),
        BST_STARTS + timedelta(minutes=30),
        # Either side of the autumn fall back.
        BST_ENDS - timedelta(minutes=30),
        BST_ENDS + timedelta(minutes=30),
        # Local midnight in BST, the moment the word should turn over.
        datetime(2026, 7, 15, 23, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 15, 23, 1, tzinfo=timezone.utc),
    ],
)
def test_polling_date_matches_the_local_date(moment):
    offset = offset_for(moment)
    assert polling_date(moment, offset) == actual_local_date(moment), (
        f"at {moment.isoformat()} with offset {offset}s"
    )


def test_the_word_turns_over_at_local_midnight_in_summer():
    """23:00 UTC is midnight BST: the date must advance exactly there."""
    before = datetime(2026, 7, 15, 22, 59, tzinfo=timezone.utc)
    after = datetime(2026, 7, 15, 23, 1, tzinfo=timezone.utc)
    assert polling_date(before, offset_for(before)) == "2026-07-15"
    assert polling_date(after, offset_for(after)) == "2026-07-16"


def test_ignoring_the_offset_would_be_wrong_in_summer():
    """Guards the reason the offset is in the URL at all."""
    moment = datetime(2026, 7, 15, 23, 30, tzinfo=timezone.utc)
    naive_utc = moment.strftime("%Y-%m-%d")
    assert naive_utc == "2026-07-15"
    assert actual_local_date(moment) == "2026-07-16"
    assert polling_date(moment, offset_for(moment)) == "2026-07-16"


def test_every_hour_across_both_transition_days():
    """A full sweep, rather than trusting the handful of points above."""
    for start in (datetime(2026, 3, 29, tzinfo=timezone.utc),
                  datetime(2026, 10, 25, tzinfo=timezone.utc)):
        for hour in range(48):
            moment = start + timedelta(hours=hour)
            offset = offset_for(moment)
            assert polling_date(moment, offset) == actual_local_date(moment), (
                f"{moment.isoformat()} offset={offset}"
            )


@pytest.mark.parametrize(
    "zone_name",
    ["Europe/London", "Asia/Tokyo", "America/New_York", "Australia/Sydney",
     "Asia/Kathmandu", "UTC"],
)
def test_holds_for_other_time_zones(zone_name):
    """Including a half-hour offset zone, which catches integer-hour bugs."""
    zone = ZoneInfo(zone_name)
    for hour in range(0, 48):
        moment = datetime(2026, 8, 9, tzinfo=timezone.utc) + timedelta(hours=hour)
        offset = offset_for(moment, zone)
        assert polling_date(moment, offset) == actual_local_date(moment, zone)
