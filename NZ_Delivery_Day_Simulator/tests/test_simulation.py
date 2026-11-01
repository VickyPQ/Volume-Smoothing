import pytest

from simulator.simulation import delivery_day_is_allowed, pick_day_from_delivery


@pytest.mark.parametrize(
    ("day", "group", "expected"),
    [
        ("Monday", "Metro", "Sunday"),
        ("Monday", "Regional", "Friday"),
        ("Friday", "Metro", "Thursday"),
    ],
)
def test_pick_day(day, group, expected):
    assert pick_day_from_delivery(day, group) == expected


def test_removed_pick_days_are_not_allowed():
    assert not delivery_day_is_allowed("Friday", "Metro")
    assert not delivery_day_is_allowed("Monday", "Regional")


def test_unknown_group_is_not_allowed():
    assert not delivery_day_is_allowed("Tuesday", "Unknown")
