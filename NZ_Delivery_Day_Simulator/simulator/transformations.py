"""Pure cleaning, normalization and delivery-day transformation helpers."""

import pandas as pd

from simulator.config import (
    ALL_DAY_ORDER, DAY_IDX, DAY_VALUE_TO_FULL, METRO_PICK_MAP,
    NUMERIC_DAY_TO_FULL, REGIONAL_PICK_MAP, REMOVED_PICK_DAY_BY_GROUP,
)

def normalize_delivery_day_value(value):
    """Normalise Delivery Day values to full weekday names.

    Handles short names, full names, and Excel-style weekday numbers 1-7.
    """
    if pd.isna(value):
        return None

    text = str(value).strip()
    if not text:
        return None

    key = text.lower()
    if key in DAY_VALUE_TO_FULL:
        return DAY_VALUE_TO_FULL[key]

    try:
        number = float(text)
        if number.is_integer():
            return NUMERIC_DAY_TO_FULL.get(str(int(number)))
    except (TypeError, ValueError, OverflowError):
        pass

    return None
def clean_text(series):

    return (
        series
        .astype("string")
        .str.strip()
    )


def normalize_customer_id(series):

    return (
        pd.to_numeric(
            series,
            errors="coerce"
        )
        .astype("Int64")
    )


def normalize_customer_group(value):

    if pd.isna(value):
        return "Unknown"

    text = str(value).strip().lower()

    # Regional Remote -> Regional
    if "regional" in text:
        return "Regional"

    if "metro" in text:
        return "Metro"

    return "Unknown"


def sort_days(days):

    return sorted(
        days,
        key=lambda d: DAY_IDX.get(d, 999)
    )


def parse_mixed_date(series):
    """Parse Billing dates safely.

    The Billing extract uses ISO dates ("2025-08-13 00:00:00.000").
    pd.to_datetime(..., dayfirst=True) mis-reads ISO dates as YYYY-DD-MM:
    days 1-12 get day/month swapped (wrong weekday) and days 13-31 become
    NaT and are dropped. Parse ISO first, then fall back to DD/MM/YYYY.
    """
    text = series.astype("string").str.strip()
    parsed = pd.to_datetime(text, format="ISO8601", errors="coerce")
    missing = parsed.isna() & text.notna() & text.ne("")
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(
            text[missing], dayfirst=True, errors="coerce", format="mixed"
        )
    return parsed


def assign_season(month):

    if month in [5, 6, 7, 8, 9]:
        return "May-Sep"

    if month in [10, 11, 12]:
        return "Oct-Dec"

    if month in [1, 2, 3, 4]:
        return "Jan-Apr"

    return "Unknown"


def pick_day_from_delivery(
    delivery_day,
    customer_group
):

    if customer_group == "Metro":

        return METRO_PICK_MAP.get(
            delivery_day
        )

    if customer_group == "Regional":

        return REGIONAL_PICK_MAP.get(
            delivery_day
        )

    return None


def delivery_day_is_allowed(
    delivery_day,
    customer_group
):

    pick_day = pick_day_from_delivery(
        delivery_day,
        customer_group
    )

    if pick_day is None:
        return False

    removed_pick_day = (
        REMOVED_PICK_DAY_BY_GROUP.get(
            customer_group
        )
    )

    if removed_pick_day is None:
        return False

    return pick_day != removed_pick_day
