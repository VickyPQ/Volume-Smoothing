"""Read and validate source files; contains no UI or Streamlit code."""

from pathlib import Path

import numpy as np
import pandas as pd

from simulator.config import *  # noqa: F403
from simulator.transformations import *  # noqa: F403

def load_data():

    # ------------------------------------------------------
    # Files
    # ------------------------------------------------------

    fact = pd.read_csv(
        "Billing_Raw.csv",
        low_memory=False
    )


    # New warehouse extract uses Total Cartons.
    # Keep backward compatibility with the earlier Total PickVolume_CLP field.
    if "Total Cartons" not in fact.columns and "Total PickVolume_CLP" in fact.columns:
        fact["Total Cartons"] = fact["Total PickVolume_CLP"]

    for optional_pick_col in [
        "Pallet Picks",
        "Layer Picks",
        "Carton Picks",
        "Keg Picks"
    ]:
        if optional_pick_col not in fact.columns:
            fact[optional_pick_col] = 0

    delivery_day = pd.read_excel(
        "Delivery Day.xlsx"
    )

    route_data = pd.read_excel(
        "Route Data.xlsx"
    )


    # ======================================================
    # REQUIRED BILLING RAW COLUMNS
    # ======================================================

    required_fact_columns = [
        "Sales Document",
        "Plant ID",
        "Route",
        "Delivery Date",
        "PickDate_Adjusted",
        "Customer ID",
        "Customer Name",
        "Total Cartons",
        "Pallet Picks",
        "Layer Picks",
        "Carton Picks",
        "Keg Picks",
        "Total Keg Qty",
        "Total Gross Weight",
        "Keg Gross Weight",
        "Carton Gross Weight"
    ]


    missing_fact = [
        c
        for c in required_fact_columns
        if c not in fact.columns
    ]


    if missing_fact:

        raise ValueError(
            "Billing_Raw.csv is missing: "
            + ", ".join(missing_fact)
        )


    # ======================================================
    # REQUIRED DELIVERY DAY COLUMNS
    # ======================================================

    required_delivery_columns = [
        "Customer ID",
        "Customer Name",
        "Route",
        "Delivery Days",
        "Customer Group",
        "Impacted Delivery Day Row"
    ]


    missing_delivery = [
        c
        for c in required_delivery_columns
        if c not in delivery_day.columns
    ]


    if missing_delivery:

        raise ValueError(
            "Delivery Day.xlsx is missing: "
            + ", ".join(missing_delivery)
        )


    # ======================================================
    # REQUIRED ROUTE DATA COLUMNS
    # ======================================================

    required_route_columns = [
        "Route",
        "Island",
        "Carrier Name",
        "Description"
    ]


    missing_route = [
        c
        for c in required_route_columns
        if c not in route_data.columns
    ]


    if missing_route:

        raise ValueError(
            "Route Data.xlsx is missing: "
            + ", ".join(missing_route)
        )


    # ======================================================
    # CLEAN BILLING RAW
    # ======================================================

    fact["Plant ID"] = pd.to_numeric(
        fact["Plant ID"],
        errors="coerce"
    )


    # Plant 1034 only

    fact = fact[
        fact["Plant ID"] == PLANT_TO_ANALYSE
    ].copy()


    if fact.empty:

        raise ValueError(
            f"No Billing_Raw rows found for "
            f"Plant {PLANT_TO_ANALYSE}."
        )


    # ------------------------------------------------------
    # Customer
    # ------------------------------------------------------

    fact["Customer ID"] = normalize_customer_id(
        fact["Customer ID"]
    )


    fact["Customer Name"] = (
        clean_text(
            fact["Customer Name"]
        )
        .fillna("Unknown Customer")
    )


    # ------------------------------------------------------
    # Route
    # ------------------------------------------------------

    fact["Route"] = (
        clean_text(
            fact["Route"]
        )
        .fillna("")
    )


    # ------------------------------------------------------
    # Delivery Date
    # DD/MM/YYYY
    # ------------------------------------------------------

    fact["Delivery Date"] = parse_mixed_date(
        fact["Delivery Date"]
    )

    # Never drop rows silently: a bad date here removes real volume.
    unparsed_delivery_dates = int(fact["Delivery Date"].isna().sum())
    if unparsed_delivery_dates:
        print(f"WARNING: {unparsed_delivery_dates:,} Billing rows have an unreadable Delivery Date and were excluded.")

    fact = fact[
        fact["Delivery Date"].notna()
    ].copy()


    fact["Delivery Day"] = (
        fact["Delivery Date"]
        .dt.day_name()
    )


    # ------------------------------------------------------
    # Pick Date
    # ------------------------------------------------------

    fact["PickDate_Adjusted"] = parse_mixed_date(
        fact["PickDate_Adjusted"]
    )


    fact["Pick Day"] = (
        fact["PickDate_Adjusted"]
        .dt.day_name()
    )


    # ------------------------------------------------------
    # Measures
    # ------------------------------------------------------

    fact["Cartons"] = pd.to_numeric(
        fact["Total Cartons"],
        errors="coerce"
    ).fillna(0)


    for pick_col in [
        "Pallet Picks",
        "Layer Picks",
        "Carton Picks",
        "Keg Picks"
    ]:
        fact[pick_col] = pd.to_numeric(
            fact[pick_col],
            errors="coerce"
        ).fillna(0)


    fact["Keg Qty"] = pd.to_numeric(
        fact["Total Keg Qty"],
        errors="coerce"
    ).fillna(0)

    fact["Gross Weight"] = pd.to_numeric(
        fact["Total Gross Weight"],
        errors="coerce"
    ).fillna(0)

    fact["Keg Gross Weight"] = pd.to_numeric(
        fact["Keg Gross Weight"],
        errors="coerce"
    ).fillna(0)

    fact["Carton Gross Weight"] = pd.to_numeric(
        fact["Carton Gross Weight"],
        errors="coerce"
    ).fillna(0)


    # ------------------------------------------------------
    # Season
    # ------------------------------------------------------

    fact["Season"] = (
        fact["Delivery Date"]
        .dt.month
        .apply(assign_season)
    )


    # ======================================================
    # CLEAN DELIVERY DAY
    # ======================================================

    delivery_day["Customer ID"] = normalize_customer_id(
        delivery_day["Customer ID"]
    )


    delivery_day["Customer Name"] = (
        clean_text(
            delivery_day["Customer Name"]
        )
        .fillna("Unknown Customer")
    )


    delivery_day["Route"] = (
        clean_text(
            delivery_day["Route"]
        )
        .fillna("")
    )


    delivery_day["Delivery Days"] = (
        clean_text(
            delivery_day["Delivery Days"]
        )
        .fillna("")
    )

    # Canonical day key used throughout the application.
    # Supports short names, full names and Excel weekday numbers.
    delivery_day["Delivery Day Full"] = delivery_day["Delivery Days"].apply(
        normalize_delivery_day_value
    )


    delivery_day["Customer Group"] = (
        delivery_day[
            "Customer Group"
        ]
        .apply(
            normalize_customer_group
        )
    )


    delivery_day[
        "Impacted Delivery Day Row"
    ] = (
        clean_text(
            delivery_day[
                "Impacted Delivery Day Row"
            ]
        )
        .fillna("")
        .str.title()
    )


    # ======================================================
    # CLEAN ROUTE DATA
    # ======================================================

    route_data["Route"] = (
        clean_text(
            route_data["Route"]
        )
        .fillna("")
    )


    route_data["Island"] = (
        clean_text(
            route_data["Island"]
        )
        .fillna("Unknown")
    )


    route_data["Carrier Name"] = (
        clean_text(
            route_data["Carrier Name"]
        )
        .fillna("Unknown Carrier")
    )


    route_data["Description"] = (
        clean_text(
            route_data["Description"]
        )
        .fillna("")
    )


    # ======================================================
    # ROUTE LOOKUP
    #
    # Route Data is source for:
    # Island
    # Carrier Name
    # Route Description
    # ======================================================

    route_lookup = (
        route_data[
            [
                "Route",
                "Island",
                "Carrier Name",
                "Description"
            ]
        ]
        .drop_duplicates(
            subset=["Route"]
        )
        .rename(
            columns={
                "Description":
                    "Route Description"
            }
        )
    )


    # ------------------------------------------------------
    # Add route attributes to Billing Raw
    # ------------------------------------------------------

    fact = fact.merge(
        route_lookup,
        on="Route",
        how="left"
    )


    fact["Island"] = (
        fact["Island"]
        .fillna("Unknown")
    )


    fact["Carrier Name"] = (
        fact["Carrier Name"]
        .fillna("Unknown Carrier")
    )


    fact["Route Description"] = (
        fact["Route Description"]
        .fillna("")
    )


    # ------------------------------------------------------
    # Add route attributes to Delivery Day
    # ------------------------------------------------------

    delivery_day = delivery_day.merge(
        route_lookup,
        on="Route",
        how="left"
    )


    delivery_day["Island"] = (
        delivery_day["Island"]
        .fillna("Unknown")
    )


    delivery_day["Carrier Name"] = (
        delivery_day["Carrier Name"]
        .fillna("Unknown Carrier")
    )


    delivery_day["Route Description"] = (
        delivery_day["Route Description"]
        .fillna("")
    )


    # ======================================================
    # CUSTOMER GROUP LOOKUP -> BILLING RAW
    # ======================================================

    customer_group_lookup = (
        delivery_day[
            [
                "Customer ID",
                "Customer Group"
            ]
        ]
        .dropna(
            subset=["Customer ID"]
        )
        .drop_duplicates(
            subset=["Customer ID"]
        )
    )


    fact = fact.merge(
        customer_group_lookup,
        on="Customer ID",
        how="left"
    )


    fact["Customer Group"] = (
        fact["Customer Group"]
        .fillna("Unknown")
    )


    return (
        fact,
        delivery_day,
        route_data
    )
