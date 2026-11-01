"""Streamlit UI for customers."""

import io

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
try:
    import pulp
except ImportError:
    pulp = None

from simulator.runtime import *  # noqa: F403
from simulator.ui.common import *  # noqa: F403

def render_customers():

    st.header(
        "Impacted Customers - North Island"
    )




    # ======================================================
    # KPIs
    # ======================================================

    total_impacted_customers = (
        impacted_customer_master[
            "Customer ID"
        ]
        .nunique()
    )


    impacted_with_volume = (
        impacted_customer_master[
            impacted_customer_master[
                "Has Billing Volume"
            ]
            ==
            True
        ][
            "Customer ID"
        ]
        .nunique()
    )


    impacted_without_volume = (
        total_impacted_customers
        -
        impacted_with_volume
    )


    i1, i2, i3, i4 = st.columns(4)


    i1.metric(
        "Impacted Customers",
        f"{total_impacted_customers:,}"
    )


    i2.metric(
        "Impacted Customers With Volume",
        f"{impacted_with_volume:,}"
    )


    i3.metric(
        "Impacted Customers Without Volume",
        f"{impacted_without_volume:,}"
    )


    i4.metric(
        "Impacted Routes",
        f"{impacted_route_master['Route'].nunique():,}"
    )


    # ======================================================
    # CUSTOMER GROUP
    # ======================================================

    st.subheader(
        "By Customer Group"
    )


    impacted_group = (
        impacted_customer_master
        .groupby(
            "Customer Group"
        )
        .agg(
            **{
                "Impacted Customers":
                    (
                        "Customer ID",
                        "nunique"
                    )
            }
        )
        .reset_index()
        .sort_values(
            "Impacted Customers",
            ascending=False
        )
    )


    st.dataframe(
        impacted_group.style.format({"Impacted Customers": "{:,.0f}"}),
        use_container_width=True,
        hide_index=True
    )


    # ======================================================
    # CARRIER
    # ======================================================

    st.subheader(
        "By Carrier"
    )


    impacted_by_carrier = (
        impacted_customer_master
        .groupby(
            [
                "Island",
                "Carrier Name"
            ]
        )
        .agg(
            **{
                "Impacted Customers":
                    (
                        "Customer ID",
                        "nunique"
                    ),

                "Impacted Routes":
                    (
                        "Route",
                        "nunique"
                    )
            }
        )
        .reset_index()
        .sort_values(
            "Impacted Customers",
            ascending=False
        )
    )


    st.dataframe(
        impacted_by_carrier.style.format({
            "Impacted Customers": "{:,.0f}",
            "Impacted Routes": "{:,.0f}"
        }),
        use_container_width=True,
        hide_index=True
    )


    fig_impacted_carrier = px.bar(
        impacted_by_carrier,
        x="Carrier Name",
        y="Impacted Customers",
        text="Impacted Customers",
        title=(
            "North Island Impacted Customers by Carrier"
        )
    )


    st.plotly_chart(
        fig_impacted_carrier,
        use_container_width=True
    )


    # ======================================================
    # ROUTE
    # ======================================================

    st.subheader(
        "By Route"
    )


    impacted_by_route = (
        impacted_customer_master
        .groupby(
            [
                "Island",
                "Carrier Name",
                "Route",
                "Route Description"
            ]
        )
        .agg(
            **{
                "Impacted Customers":
                    (
                        "Customer ID",
                        "nunique"
                    )
            }
        )
        .reset_index()
        .sort_values(
            "Impacted Customers",
            ascending=False
        )
    )


    st.dataframe(
        impacted_by_route.style.format({"Impacted Customers": "{:,.0f}"}),
        use_container_width=True,
        hide_index=True
    )


    # ======================================================
    # DETAIL
    # ======================================================

    st.subheader(
        "Impacted Customer Detail"
    )


    impacted_customer_detail = (
        impacted_customer_master
        .merge(
            delivery_day_count,
            on="Customer ID",
            how="left"
        )
    )


    impacted_customer_detail[
        "# Delivery Days"
    ] = (
        impacted_customer_detail[
            "# Delivery Days"
        ]
        .fillna(0)
        .astype(int)
    )


    st.dataframe(
        impacted_customer_detail[[
            "Customer ID",
            "Customer Name",
            "# Delivery Days",
            "Customer Group",
            "Island",
            "Carrier Name",
            "Route",
            "Route Description",
            "Has Billing Volume"
        ]].style.format({"# Delivery Days": "{:,.0f}"}),
        use_container_width=True,
        hide_index=True
    )
