"""Streamlit UI for network."""

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

def render_network():

    st.header(
        "Current Network Overview"
    )

    st.info(
        "Transport uses all historical Billing rows whose Route + Delivery Day matches a current "
        "route operating day from the Delivery Day table. Planning uses the stricter Customer ID + Route + Delivery Day match."
    )


    # ======================================================
    # KPIs
    # ======================================================

    n1, n2, n3 = st.columns(3)


    n1.metric(
        "Network Customers",
        f"{fact['Customer ID'].nunique():,}"
    )


    n2.metric(
        "Network Carriers",
        f"{network_route_master['Carrier Name'].nunique():,}"
    )


    n3.metric(
        "Network Routes",
        f"{network_route_master['Route'].nunique():,}"
    )


    st.divider()


    # ======================================================
    # CARRIER
    # ======================================================

    st.subheader(
        "Carrier Overview"
    )


    network_carriers = sorted(
        network_route_master[
            "Carrier Name"
        ]
        .dropna()
        .unique()
        .tolist()
    )


    selected_carrier = st.selectbox(
        "Select carrier",
        network_carriers,
        key="network_carrier"
    )


    carrier_routes = (
        network_route_master[
            network_route_master[
                "Carrier Name"
            ]
            ==
            selected_carrier
        ][
            [
                "Island",
                "Route",
                "Route Description"
            ]
        ]
        .drop_duplicates()
        .sort_values(
            "Route"
        )
    )


    carrier_network_customers = (
        descriptive_transport_fact[
            descriptive_transport_fact["Carrier Name"].eq(selected_carrier)
        ]["Customer ID"]
        .nunique()
    )


    carrier_total_weight = (
        route_day_volume[
            route_day_volume[
                "Carrier Name"
            ]
            ==
            selected_carrier
        ][
            "Gross Weight"
        ]
        .sum()
    )


    # ------------------------------------------------------
    # Carrier weight reconciliation
    # ------------------------------------------------------
    carrier_historical_weight = float(
        fact.loc[
            fact["Carrier Name"].eq(selected_carrier),
            "Gross Weight"
        ].sum()
    )
    carrier_operating_weight = float(
        descriptive_transport_fact.loc[
            descriptive_transport_fact["Carrier Name"].eq(selected_carrier),
            "Gross Weight"
        ].sum()
    )
    carrier_planning_weight = float(
        planning_fact.loc[
            planning_fact["Carrier Name"].eq(selected_carrier),
            "Gross Weight"
        ].sum()
    )

    with st.expander("Carrier weight reconciliation", expanded=False):
        carrier_recon = pd.DataFrame([
            {
                "Measure": "All historical Billing weight",
                "Gross Weight": carrier_historical_weight
            },
            {
                "Measure": "Route + Delivery Day operating-day weight",
                "Gross Weight": carrier_operating_weight
            },
            {
                "Measure": "Exact Customer + Route + Delivery Day planning weight",
                "Gross Weight": carrier_planning_weight
            }
        ])
        st.dataframe(
            carrier_recon.style.format({"Gross Weight": "{:,.2f}"}),
            use_container_width=True,
            hide_index=True
        )

        if carrier_operating_weight + 0.01 < carrier_planning_weight:
            st.error(
                "Data reconciliation error: strict Customer + Route + Delivery Day "
                "planning weight is larger than the Route + Delivery Day operating-day "
                "weight. Check delivery-day values and source data."
            )

    # ======================================================
    # CARRIER CHARTS
    # ======================================================

    carrier_chart = (
        carrier_day_volume[
            carrier_day_volume["Carrier Name"] == selected_carrier
        ]
        .groupby("Delivery Day", observed=True)
        .agg({
            "Gross Weight": "sum",
            "Keg Qty": "sum",
            "Keg Gross Weight": "sum",
            "Carton Gross Weight": "sum"
        })
        .reset_index()
    )

    carrier_chart["Carrier Total Weight"] = carrier_chart["Gross Weight"].sum()
    carrier_chart["Carrier Total Keg Qty"] = carrier_chart["Keg Qty"].sum()
    carrier_chart["Carrier Day Share"] = (
        carrier_chart["Gross Weight"]
        / carrier_chart["Carrier Total Weight"].replace(0, pd.NA)
    )
    carrier_chart["Carrier Keg Day Share"] = (
        carrier_chart["Keg Qty"]
        / carrier_chart["Carrier Total Keg Qty"].replace(0, pd.NA)
    )
    carrier_chart["Delivery Day"] = pd.Categorical(
        carrier_chart["Delivery Day"],
        categories=ROUTE_DAY_ORDER,
        ordered=True
    )
    carrier_chart = carrier_chart.sort_values("Delivery Day")

    fig_carrier = px.bar(
        carrier_chart,
        x="Delivery Day",
        y="Gross Weight",
        text="Carrier Day Share",
        title=f"{selected_carrier} - Gross Weight by Delivery Day"
    )
    fig_carrier.update_traces(texttemplate="%{text:.1%}", textposition="outside")
    st.plotly_chart(fig_carrier, use_container_width=True)

    fig_carrier_keg_volume = px.bar(
        carrier_chart,
        x="Delivery Day",
        y="Keg Qty",
        text="Carrier Keg Day Share",
        title=f"{selected_carrier} - Keg Volume by Delivery Day"
    )
    fig_carrier_keg_volume.update_traces(texttemplate="%{text:.1%}", textposition="outside")
    fig_carrier_keg_volume.update_yaxes(tickformat=",", title="Keg Qty")
    st.plotly_chart(fig_carrier_keg_volume, use_container_width=True)

    st.dataframe(
        carrier_chart[[
            "Delivery Day",
            "Gross Weight",
            "Carrier Day Share",
            "Carton Gross Weight",
            "Keg Gross Weight",
            "Keg Qty",
            "Carrier Keg Day Share"
        ]].style.format({
            "Gross Weight": "{:,.0f}",
            "Carrier Day Share": "{:.1%}",
            "Carton Gross Weight": "{:,.0f}",
            "Keg Gross Weight": "{:,.0f}",
            "Keg Qty": "{:,.0f}",
            "Carrier Keg Day Share": "{:.1%}"
        }),
        use_container_width=True,
        hide_index=True
    )

    carrier_mix = carrier_chart[[
        "Delivery Day", "Carton Gross Weight", "Keg Gross Weight"
    ]].copy()
    carrier_mix["Weight Mix Total"] = (
        carrier_mix["Carton Gross Weight"] + carrier_mix["Keg Gross Weight"]
    )
    for col in ["Carton Gross Weight", "Keg Gross Weight"]:
        carrier_mix[f"{col} Share"] = (
            carrier_mix[col] / carrier_mix["Weight Mix Total"].replace(0, pd.NA)
        ).fillna(0.0)

    carrier_mix_long = carrier_mix.melt(
        id_vars=["Delivery Day"],
        value_vars=["Carton Gross Weight Share", "Keg Gross Weight Share"],
        var_name="Weight Type",
        value_name="Share"
    )
    carrier_mix_long["Weight Type"] = carrier_mix_long["Weight Type"].str.replace(
        " Gross Weight Share", "", regex=False
    )
    fig_carrier_mix = px.bar(
        carrier_mix_long,
        x="Delivery Day",
        y="Share",
        color="Weight Type",
        barmode="stack",
        text="Share",
        title=f"{selected_carrier} - Carton vs Keg Weight Mix"
    )
    fig_carrier_mix.update_traces(texttemplate="%{text:.1%}", textposition="inside")
    fig_carrier_mix.update_yaxes(tickformat=".0%", range=[0, 1])
    st.plotly_chart(fig_carrier_mix, use_container_width=True)



    # ======================================================
    # ROUTE
    # ======================================================

    carrier_routes[
        "Label"
    ] = (
        carrier_routes[
            "Route"
        ]
        +
        " - "
        +
        carrier_routes[
            "Route Description"
        ]
        .fillna("")
    )


    selected_route_label = st.selectbox(
        "Select route",
        carrier_routes[
            "Label"
        ]
        .tolist(),
        key="network_route"
    )


    selected_route = (
        carrier_routes.loc[
            carrier_routes[
                "Label"
            ]
            ==
            selected_route_label,
            "Route"
        ]
        .iloc[0]
    )


    selected_route_island = (
        carrier_routes.loc[
            carrier_routes[
                "Route"
            ]
            ==
            selected_route,
            "Island"
        ]
        .iloc[0]
    )


    selected_description = (
        carrier_routes.loc[
            carrier_routes[
                "Route"
            ]
            ==
            selected_route,
            "Route Description"
        ]
        .iloc[0]
    )




    selected_set_days = (
        route_days.get(
            selected_route,
            []
        )
    )


    if selected_set_days:

        st.info(
            "Configured Delivery Days: "
            +
            ", ".join(
                selected_set_days
            )
        )


    # ======================================================
    # ROUTE VOLUME
    # ======================================================

    route_chart = (
        route_day_volume[
            route_day_volume["Route"].eq(selected_route)
            & route_day_volume["Is_Set_Day"].eq(True)
        ]
        .copy()
    )

    route_chart["Delivery Day"] = pd.Categorical(
        route_chart["Delivery Day"],
        categories=ROUTE_DAY_ORDER,
        ordered=True
    )
    route_chart = route_chart.sort_values("Delivery Day")

    fig_route = px.bar(
        route_chart,
        x="Delivery Day",
        y="Gross Weight",
        text="Route Day Share",
        title=f"{selected_route} - Gross Weight by Delivery Day"
    )
    fig_route.update_traces(texttemplate="%{text:.1%}", textposition="outside")
    st.plotly_chart(fig_route, use_container_width=True)

    route_mix = route_chart[[
        "Delivery Day", "Carton Gross Weight", "Keg Gross Weight"
    ]].copy()
    route_mix["Weight Mix Total"] = route_mix["Carton Gross Weight"] + route_mix["Keg Gross Weight"]
    for col in ["Carton Gross Weight", "Keg Gross Weight"]:
        route_mix[f"{col} Share"] = (
            route_mix[col] / route_mix["Weight Mix Total"].replace(0, pd.NA)
        ).fillna(0.0)

    route_mix_long = route_mix.melt(
        id_vars=["Delivery Day"],
        value_vars=["Carton Gross Weight Share", "Keg Gross Weight Share"],
        var_name="Weight Type",
        value_name="Share"
    )
    route_mix_long["Weight Type"] = route_mix_long["Weight Type"].str.replace(
        " Gross Weight Share", "", regex=False
    )
    fig_route_mix = px.bar(
        route_mix_long,
        x="Delivery Day",
        y="Share",
        color="Weight Type",
        barmode="stack",
        text="Share",
        title=f"{selected_route} - Carton vs Keg Weight Mix"
    )
    fig_route_mix.update_traces(texttemplate="%{text:.1%}", textposition="inside")
    fig_route_mix.update_yaxes(tickformat=".0%", range=[0, 1])
    st.plotly_chart(fig_route_mix, use_container_width=True)

    fig_route_keg_volume = px.bar(
        route_chart,
        x="Delivery Day",
        y="Keg Qty",
        text="Route Keg Day Share",
        title=f"{selected_route} - Keg Volume by Delivery Day"
    )
    fig_route_keg_volume.update_traces(texttemplate="%{text:.1%}", textposition="outside")
    fig_route_keg_volume.update_yaxes(tickformat=",", title="Keg Qty")
    st.plotly_chart(fig_route_keg_volume, use_container_width=True)

    st.dataframe(
        route_chart[[
            "Delivery Day",
            "Gross Weight",
            "Route Day Share",
            "Carton Gross Weight",
            "Keg Gross Weight",
            "Keg Qty",
            "Route Keg Day Share"
        ]].style.format({
            "Gross Weight": "{:,.0f}",
            "Route Day Share": "{:.1%}",
            "Carton Gross Weight": "{:,.0f}",
            "Keg Gross Weight": "{:,.0f}",
            "Keg Qty": "{:,.0f}",
            "Route Keg Day Share": "{:.1%}"
        }),
        use_container_width=True,
        hide_index=True
    )

    # ======================================================
    # CUSTOMERS ON ROUTE
    # ======================================================

    st.subheader(
        "Customers on Route"
    )


    network_customers_route = (
        descriptive_transport_fact[
            descriptive_transport_fact["Route"].eq(selected_route)
        ][[
            "Customer ID",
            "Customer Name",
            "Customer Group"
        ]]
        .drop_duplicates()
    )


    network_customers_route = (
        network_customers_route
        .merge(
            delivery_day_count,
            on="Customer ID",
            how="left"
        )
    )


    network_customers_route[
        "# Delivery Days"
    ] = (
        network_customers_route[
            "# Delivery Days"
        ]
        .fillna(0)
        .astype(int)
    )


    st.dataframe(
        network_customers_route[[
            "Customer ID",
            "Customer Name",
            "# Delivery Days",
            "Customer Group"
        ]].style.format({"# Delivery Days": "{:,.0f}"}),
        use_container_width=True,
        hide_index=True
    )


    # ======================================================
    # WAREHOUSE CURRENT NETWORK
    # ======================================================

    st.divider()

    st.header("Current Warehouse Pick Volume")

    season_selection = st.selectbox(
        "Season",
        ["All Seasons"] + SEASON_ORDER,
        key="warehouse_season"
    )

    if season_selection == "All Seasons":
        wh_selected = warehouse_all.copy()
    else:
        wh_selected = warehouse_season[
            warehouse_season["Season"].eq(season_selection)
        ].copy()

    wh_selected = wh_selected[
        wh_selected["Customer Group"].isin(["Metro", "Regional"])
    ].copy()

    warehouse_combined = (
        wh_selected
        .groupby("Pick Day", observed=True)[WAREHOUSE_MEASURES]
        .sum()
        .reindex(WAREHOUSE_DAY_ORDER, fill_value=0)
        .reset_index()
    )

    for measure in WAREHOUSE_MEASURES:
        warehouse_combined[measure] = pd.to_numeric(
            warehouse_combined[measure], errors="coerce"
        ).fillna(0.0)

    st.dataframe(
        warehouse_combined[[
            "Pick Day", "Cartons", "Pallet Picks", "Layer Picks", "Carton Picks", "Keg Picks"
        ]].rename(columns={"Cartons": "Total Cartons"}).style.format({
            "Total Cartons": "{:,.0f}",
            "Pallet Picks": "{:,.0f}",
            "Layer Picks": "{:,.0f}",
            "Carton Picks": "{:,.0f}",
            "Keg Picks": "{:,.0f}"
        }),
        use_container_width=True,
        hide_index=True
    )

    volume_chart = warehouse_combined.copy()
    volume_chart["Pick Day"] = pd.Categorical(
        volume_chart["Pick Day"],
        categories=WAREHOUSE_DAY_ORDER,
        ordered=True
    )

    total_cartons = float(volume_chart["Cartons"].sum())
    volume_chart["Carton Share"] = (
        volume_chart["Cartons"] / total_cartons if total_cartons > 0 else 0.0
    )

    fig_wh = px.bar(
        volume_chart.sort_values("Pick Day"),
        x="Pick Day",
        y="Cartons",
        text="Carton Share",
        title=f"Current Warehouse Total Carton Volume - {season_selection}",
        labels={"Cartons": "Total Cartons"}
    )
    fig_wh.update_traces(texttemplate="%{text:.1%}", textposition="outside")
    st.plotly_chart(fig_wh, use_container_width=True)

    st.subheader("Warehouse Pick Mix")

    pick_mix = warehouse_combined[[
        "Pick Day", "Pallet Picks", "Layer Picks", "Carton Picks"
    ]].copy()
    pick_mix["Pick Mix Total"] = (
        pick_mix["Pallet Picks"] + pick_mix["Layer Picks"] + pick_mix["Carton Picks"]
    )

    for measure in ["Pallet Picks", "Layer Picks", "Carton Picks"]:
        pick_mix[f"{measure} %"] = (
            pick_mix[measure] / pick_mix["Pick Mix Total"].replace(0, pd.NA)
        ).fillna(0.0)

    st.dataframe(
        pick_mix[[
            "Pick Day",
            "Pallet Picks", "Pallet Picks %",
            "Layer Picks", "Layer Picks %",
            "Carton Picks", "Carton Picks %"
        ]].style.format({
            "Pallet Picks": "{:,.0f}",
            "Pallet Picks %": "{:.1%}",
            "Layer Picks": "{:,.0f}",
            "Layer Picks %": "{:.1%}",
            "Carton Picks": "{:,.0f}",
            "Carton Picks %": "{:.1%}"
        }),
        use_container_width=True,
        hide_index=True
    )

    pick_mix_long = pick_mix[[
        "Pick Day", "Pallet Picks %", "Layer Picks %", "Carton Picks %"
    ]].melt(
        id_vars="Pick Day",
        var_name="Pick Method",
        value_name="Share"
    )
    pick_mix_long["Pick Method"] = pick_mix_long["Pick Method"].str.replace(" %", "", regex=False)
    pick_mix_long["Pick Day"] = pd.Categorical(
        pick_mix_long["Pick Day"],
        categories=WAREHOUSE_DAY_ORDER,
        ordered=True
    )

    fig_method = px.bar(
        pick_mix_long.sort_values("Pick Day"),
        x="Pick Day",
        y="Share",
        color="Pick Method",
        barmode="stack",
        text="Share",
        title=f"Warehouse Pick Mix - {season_selection}",
        labels={"Share": "% of Daily Carton Picking"}
    )
    fig_method.update_traces(texttemplate="%{text:.1%}", textposition="inside")
    fig_method.update_yaxes(tickformat=".0%", range=[0, 1])
    st.plotly_chart(fig_method, use_container_width=True)
