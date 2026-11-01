import pandas as pd

from simulator.transformations import (
    normalize_customer_group,
    normalize_delivery_day_value,
    parse_mixed_date,
)


def test_normalize_delivery_day_values():
    assert normalize_delivery_day_value("Fri") == "Friday"
    assert normalize_delivery_day_value("1") == "Monday"
    assert normalize_delivery_day_value(7) == "Sunday"


def test_normalize_customer_group():
    assert normalize_customer_group("Metro") == "Metro"
    assert normalize_customer_group("Remote Regional") == "Regional"
    assert normalize_customer_group(None) == "Unknown"


def test_parse_iso_dates_without_day_month_swap():
    parsed = parse_mixed_date(pd.Series(["2025-08-13 00:00:00.000"]))
    assert parsed.iloc[0].date().isoformat() == "2025-08-13"
