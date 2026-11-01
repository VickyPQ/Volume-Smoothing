"""Application data orchestration and cached calculation boundaries."""

import numpy as np
import pandas as pd
import streamlit as st

from simulator.aggregations import (
    build_aggregations as _build_aggregations,
    carrier_benefit_base as _carrier_benefit_base,
    carrier_benefit_route_days,
)
from simulator.config import *  # noqa: F403
from simulator.data_loader import load_data as _load_data
from simulator.simulation import *  # noqa: F403
from simulator.transformations import *  # noqa: F403

load_data = st.cache_data(_load_data)
build_aggregations = st.cache_data(_build_aggregations)
carrier_benefit_base = st.cache_data(_carrier_benefit_base)

# LOAD
# ==========================================================

try:

    fact, delivery_day, route_data = load_data()

except Exception as e:

    st.error(
        f"Unable to load source data: {e}"
    )

    st.stop()


# ==========================================================
# IMPACTED POPULATION
#
# SOURCE OF TRUTH = BUSINESS RULE
#
# Metro Friday delivery is removed.
# Regional Monday delivery is removed.
#
# `Impacted Delivery Day Row` is retained as a reconciliation /
# data-quality field, rather than being the only driver of scope.
# ==========================================================

# Delivery Day Full was created during load_data() cleaning.
# Re-normalise defensively so this remains the single canonical day key.
delivery_day["Delivery Day Full"] = delivery_day["Delivery Day Full"].apply(
    normalize_delivery_day_value
)

delivery_day["Business Rule Impacted"] = (
    (
        delivery_day["Customer Group"].eq("Metro")
        & delivery_day["Delivery Day Full"].eq("Friday")
    )
    |
    (
        delivery_day["Customer Group"].eq("Regional")
        & delivery_day["Delivery Day Full"].eq("Monday")
    )
)

impacted = (
    delivery_day[
        delivery_day["Business Rule Impacted"].eq(True)
        & delivery_day["Island"].eq(IMPACT_ISLAND)
    ]
    .copy()
)

# Compare the embedded business rule with the existing Excel impact flag.
impact_flag_reconciliation = (
    delivery_day[delivery_day["Island"].eq(IMPACT_ISLAND)]
    .assign(
        Excel_Impact_Flag=lambda x: x["Impacted Delivery Day Row"].eq("Yes")
    )
    .groupby(
        ["Business Rule Impacted", "Excel_Impact_Flag"],
        observed=True
    )
    .agg(
        Customers=("Customer ID", "nunique"),
        Routes=("Route", "nunique")
    )
    .reset_index()
)

# ==========================================================
# IMPACTED CUSTOMER MASTER
# NORTH ISLAND ONLY
# ==========================================================

impacted_customer_master = (
    impacted[
        [
            "Customer ID",
            "Customer Name",
            "Customer Group",
            "Island",
            "Carrier Name",
            "Route",
            "Route Description"
        ]
    ]
    .drop_duplicates()
)


# ==========================================================
# IMPACTED ROUTE MASTER
# NORTH ISLAND ONLY
# ==========================================================

impacted_route_master = (
    impacted[
        [
            "Island",
            "Carrier Name",
            "Route",
            "Route Description"
        ]
    ]
    .drop_duplicates()
)


# ==========================================================
# HISTORICAL BILLING CUSTOMERS
# ==========================================================

billing_customers = set(
    fact[
        "Customer ID"
    ]
    .dropna()
    .astype(int)
    .unique()
)


impacted_customer_master[
    "Has Billing Volume"
] = (
    impacted_customer_master[
        "Customer ID"
    ]
    .isin(
        billing_customers
    )
)


# ==========================================================
# INITIAL HISTORICAL ROUTE MASTER
#
# This is rebuilt below after Route + Delivery Day operating-day matching so
# Tab 1 selectors/counts use the same descriptive transport population.
# ==========================================================

network_route_master = (
    fact[
        [
            "Island",
            "Carrier Name",
            "Route",
            "Route Description"
        ]
    ]
    .loc[
        lambda x:
            x["Route"] != ""
    ]
    .drop_duplicates()
)


# ==========================================================
# ROUTE SET DELIVERY DAYS
#
# Source = Delivery Day
# Remove customer lens
# Normalise short/full day names first, then keep unique Route + Delivery Day.
# ==========================================================

route_set_days = delivery_day[["Route", "Delivery Day Full"]].copy()
route_set_days = route_set_days.rename(columns={"Delivery Day Full": "Delivery Day"})

route_set_days = (
    route_set_days[["Route", "Delivery Day"]]
    .loc[lambda x: x["Route"].ne("")]
    .loc[lambda x: x["Delivery Day"].isin(ROUTE_DAY_ORDER)]
    .drop_duplicates()
    .reset_index(drop=True)
)


route_days = (
    route_set_days
    .groupby(
        "Route"
    )[
        "Delivery Day"
    ]
    .apply(
        lambda s:
            sort_days(
                s.unique().tolist()
            )
    )
    .to_dict()
)


# ==========================================================
# FACT ROWS ON ROUTE SET DELIVERY DAYS
# ==========================================================

fact_set_delivery = fact.merge(
    route_set_days.assign(
        Is_Set_Delivery_Day=True
    ),
    on=[
        "Route",
        "Delivery Day"
    ],
    how="left"
)


fact_set_delivery[
    "Is_Set_Delivery_Day"
] = (
    fact_set_delivery[
        "Is_Set_Delivery_Day"
    ]
    .eq(True)
)


fact_set_delivery = (
    fact_set_delivery[
        fact_set_delivery[
            "Is_Set_Delivery_Day"
        ]
    ]
    .copy()
)

# ==========================================================
# TAB 1 DESCRIPTIVE TRANSPORT POPULATION
#
# Business logic:
# - Keep ALL historical Plant 1034 Billing rows whose historical Delivery Day
#   is an operating/configured day for that Route.
# - Matching grain = Route + Delivery Day only.
# - Customer ID is deliberately NOT used here because Tab 1 describes what
#   historically moved on valid route operating days, including customers
#   whose current customer-level settings may have since changed.
# - Warehouse descriptive views continue to use the full historical fact
#   dataframe because they describe actual physical pick activity.
# ==========================================================

descriptive_transport_fact = fact_set_delivery.copy()

# Rebuild the Tab 1 route master from the matched historical transport
# population so route/carrier selectors and counts align to the same scope.
network_route_master = (
    descriptive_transport_fact[[
        "Island",
        "Carrier Name",
        "Route",
        "Route Description"
    ]]
    .loc[lambda x: x["Route"].ne("")]
    .drop_duplicates()
)


# ==========================================================
# CURRENT ACTIVE PLANNING POPULATION
#
# Business logic:
# - Tab 1 descriptive analysis keeps ALL historical Plant 1034 facts.
# - Planning / optimisation uses ONLY historical Billing rows that match
#   a CURRENT customer setting in Delivery Day.xlsx on:
#       Customer ID + Route + Delivery Day
# - This is intentionally strict: a historical transaction is included
#   in the future-planning baseline only when the same customer is still
#   configured on the same route and delivery day today.
# - Historical rows that do not match the current setting remain visible
#   in Tab 1 but are excluded from future-state optimisation.
# ==========================================================

current_customer_day_master = (
    delivery_day[[
        "Customer ID",
        "Route",
        "Delivery Day Full"
    ]]
    .dropna(subset=["Customer ID"])
    .copy()
    .rename(columns={"Delivery Day Full": "Delivery Day"})
)

current_customer_day_master = (
    current_customer_day_master[[
        "Customer ID",
        "Route",
        "Delivery Day"
    ]]
    .loc[lambda x: x["Route"].ne("")]
    .loc[lambda x: x["Delivery Day"].isin(ROUTE_DAY_ORDER)]
    .drop_duplicates()
)

# Audit every Billing row against the exact CURRENT customer setting.
fact_planning_audit = fact.merge(
    current_customer_day_master.assign(Is_Current_Customer_Day=True),
    on=["Customer ID", "Route", "Delivery Day"],
    how="left",
    validate="many_to_one"
)

fact_planning_audit["Is_Current_Customer_Day"] = (
    fact_planning_audit["Is_Current_Customer_Day"].eq(True)
)

fact_planning_audit["Planning Population Status"] = np.where(
    fact_planning_audit["Is_Current_Customer_Day"],
    "Included - exact current Customer + Route + Delivery Day setting",
    "Excluded - historical row not in current Customer + Route + Delivery Day setting"
)

# Strict planning population used by scenario / optimisation / negotiation.
planning_fact = (
    fact_planning_audit[
        fact_planning_audit["Is_Current_Customer_Day"]
    ]
    .drop(columns=[
        "Is_Current_Customer_Day",
        "Planning Population Status"
    ])
    .copy()
)

# ==========================================================
# PLANNING PICK DAY
#
# IMPORTANT BUSINESS LOGIC:
# - Tab 1 keeps the ACTUAL historical PickDate_Adjusted / Pick Day so the
#   descriptive view shows what physically happened.
# - The optimisation model uses the CURRENT Customer + Route + Delivery Day
#   setting as the planning truth. Therefore its warehouse pick day is
#   MODELLED from Delivery Day + Customer Group.
#
# This keeps Shift 5 internally consistent:
#   Metro Friday delivery    -> Thursday planning pick -> Shift 5
#   Regional Monday delivery -> Friday planning pick   -> Shift 5
#
# Once those impacted settings are reassigned, their workload must leave
# Shift 5 and move into Shift 1-4.
# ==========================================================

planning_fact["Historical Pick Day"] = planning_fact["Pick Day"]
planning_fact["Planning Pick Day"] = planning_fact.apply(
    lambda row: pick_day_from_delivery(
        row["Delivery Day"],
        row["Customer Group"]
    ),
    axis=1
)

# Planning / optimisation functions already use the column name "Pick Day".
# Replace it ONLY in planning_fact with the modelled planning pick day.
# The original fact dataframe remains unchanged for Tab 1 descriptive analysis.
planning_fact["Pick Day"] = planning_fact["Planning Pick Day"]

excluded_planning_fact = (
    fact_planning_audit[
        ~fact_planning_audit["Is_Current_Customer_Day"]
    ]
    .copy()
)

# Customer-level reconciliation is kept mutually exclusive.
# A customer is counted as "matched" if at least one historical Billing row
# matches a current Customer + Route + Delivery Day setting.
billing_customer_ids = set(
    fact["Customer ID"].dropna().astype(int).unique().tolist()
)
matched_customer_ids = set(
    planning_fact["Customer ID"].dropna().astype(int).unique().tolist()
)
no_match_customer_ids = billing_customer_ids - matched_customer_ids

# Current planning routes come from the current Delivery Day master,
# including routes with zero historical activity.
planning_route_master = (
    delivery_day[[
        "Island",
        "Carrier Name",
        "Route",
        "Route Description"
    ]]
    .loc[lambda x: x["Route"].ne("")]
    .drop_duplicates()
)

# Compact reconciliation used in the optimisation tab.
planning_population_reconciliation = pd.DataFrame([
    {
        "Population": "Historical Billing population",
        "Customers": int(len(billing_customer_ids)),
        "Cartons": float(fact["Cartons"].sum()),
        "Gross Weight": float(fact["Gross Weight"].sum())
    },
    {
        "Population": "Exact current-setting planning data",
        "Customers": int(len(matched_customer_ids)),
        "Cartons": float(planning_fact["Cartons"].sum()),
        "Gross Weight": float(planning_fact["Gross Weight"].sum())
    },
    {
        "Population": "Billing customers with no exact current-setting match",
        "Customers": int(len(no_match_customer_ids)),
        "Cartons": float(
            fact.loc[fact["Customer ID"].isin(no_match_customer_ids), "Cartons"].sum()
        ),
        "Gross Weight": float(
            fact.loc[fact["Customer ID"].isin(no_match_customer_ids), "Gross Weight"].sum()
        )
    }
])

# ==========================================================
# AGGREGATIONS
# ==========================================================


(
    route_day_volume,
    carrier_day_volume,
    customer_delivery_pick,
    warehouse_season,
    warehouse_all
) = build_aggregations(
    fact,
    fact_set_delivery,
    network_route_master,
    route_set_days
)

# Future-state planning / optimisation aggregations.
# These use only rows that match the CURRENT Customer + Route + Delivery Day
# setting, and planning_fact["Pick Day"] is the MODELLED pick day derived from
# that current delivery setting. Tab 1 continues to use actual historical pick
# dates from the untouched fact dataframe.
(
    planning_route_day_volume,
    planning_carrier_day_volume,
    planning_customer_delivery_pick,
    planning_warehouse_season,
    planning_warehouse_all
) = build_aggregations(
    planning_fact,
    planning_fact,
    planning_route_master,
    route_set_days
)


# ==========================================================

delivery_day_count = (
    delivery_day[
        delivery_day["Delivery Day Full"].isin(ROUTE_DAY_ORDER)
    ]
    .groupby(
        "Customer ID"
    )[
        "Delivery Day Full"
    ]
    .nunique()
    .rename(
        "# Delivery Days"
    )
    .reset_index()
)



# ==========================================================
# CARRIER BENEFIT - CALCULATIONS
# ==========================================================
# One "run"  = a route operating on one delivery date (one truck trip).
# One "drop" = one customer delivered on one delivery date (one stop).
# Everything is shown PER WEEK, using the planning population
# (exact current Customer + Route + Delivery Day), North Island only.

CB_COLUMNS = ["Runs", "Drops", "Gross Weight", "Keg Qty"]
