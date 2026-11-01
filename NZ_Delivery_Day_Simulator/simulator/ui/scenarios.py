"""Streamlit UI for scenarios."""

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

def render_scenarios():

    st.header("Scenario Simulation - North Island")

    warehouse_base_state = build_warehouse_state(planning_warehouse_all)

    impacted_carriers = sorted(
        impacted_route_master.loc[
            impacted_route_master["Island"].eq(IMPACT_ISLAND),
            "Carrier Name"
        ].dropna().unique().tolist()
    )

    if not impacted_carriers:
        st.warning("No North Island impacted carriers available.")
    else:
        simulation_carrier = st.selectbox(
            "1. Select North Island carrier",
            impacted_carriers,
            key="simulation_carrier"
        )

        simulation_routes = (
            impacted_route_master[
                impacted_route_master["Carrier Name"].eq(simulation_carrier)
                & impacted_route_master["Island"].eq(IMPACT_ISLAND)
            ][["Island", "Route", "Route Description"]]
            .drop_duplicates()
            .sort_values("Route")
        )

        simulation_routes["Label"] = (
            simulation_routes["Route"]
            + " - "
            + simulation_routes["Route Description"].fillna("")
        )

        simulation_route_label = st.selectbox(
            "2. Select route",
            simulation_routes["Label"].tolist(),
            key="simulation_route"
        )

        simulation_route = simulation_routes.loc[
            simulation_routes["Label"].eq(simulation_route_label),
            "Route"
        ].iloc[0]

        route_customers = (
            impacted_customer_master[
                impacted_customer_master["Route"].eq(simulation_route)
                & impacted_customer_master["Island"].eq(IMPACT_ISLAND)
            ][[
                "Customer ID",
                "Customer Name",
                "Customer Group",
                "Has Billing Volume"
            ]]
            .drop_duplicates()
        )

        route_customers["Label"] = (
            route_customers["Customer ID"].astype(str)
            + " - "
            + route_customers["Customer Name"].astype(str)
        )

        customer_lookup = dict(zip(
            route_customers["Label"],
            route_customers["Customer ID"]
        ))

        selected_customer_labels = st.multiselect(
            "3. Select impacted customers",
            sorted(customer_lookup.keys()),
            key="simulation_customers"
        )

        if selected_customer_labels:
            scenario_rows = []
            # Each customer is ranked against the warehouse AFTER the moves chosen
            # for the customers listed above it, so several customers are not all
            # pushed onto the same underloaded day.
            running_wh_state = warehouse_base_state.copy()
            available_route_days = route_days.get(simulation_route, [])

            for label in selected_customer_labels:
                customer_id = int(customer_lookup[label])
                customer_name = label.split(" - ", 1)[1]

                customer_rows = impacted[
                    impacted["Customer ID"].eq(customer_id)
                    & impacted["Route"].eq(simulation_route)
                    & impacted["Island"].eq(IMPACT_ISLAND)
                ].copy()

                if customer_rows.empty:
                    st.warning(f"{label}: customer not found in impacted population.")
                    continue

                customer_group = customer_rows["Customer Group"].iloc[0]
                customer_has_volume = customer_id in billing_customers

                impacted_full_days = sort_days(
                    customer_rows.loc[
                        customer_rows["Delivery Day Full"].isin(ROUTE_DAY_ORDER),
                        "Delivery Day Full"
                    ]
                    .dropna()
                    .unique()
                    .tolist()
                )

                if not impacted_full_days:
                    st.warning(f"{label}: no impacted delivery day found.")
                    continue

                old_day = impacted_full_days[0]
                scheduled_current_pick = pick_day_from_delivery(old_day, customer_group)

                valid_new_days = [
                    day
                    for day in available_route_days
                    if day != old_day
                    and delivery_day_is_allowed(day, customer_group)
                ]

                profile, configured_days, total_hist_weight = get_customer_delivery_profile(
                    customer_id,
                    simulation_route,
                    delivery_day,
                    fact
                )

                st.markdown(f"### {customer_name} ({customer_id})")

                volume_status = (
                    "Has historical Billing volume"
                    if customer_has_volume
                    else "No historical Billing volume"
                )


                p1, p2 = st.columns([1, 3])
                p1.metric("Configured Delivery Days", f"{len(configured_days):,}")
                p1.metric("Historical Set-Day Weight", f"{total_hist_weight:,.0f} kg")

                with p2:
                    st.write("**Historical delivery-day utilisation**")
                    st.dataframe(
                        profile.style.format({
                            "Historical Gross Weight": "{:,.0f}",
                            "Share %": "{:.1%}"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )
                # --------------------------------------------------
                # Candidate recommendation table
                # --------------------------------------------------
                # IMPORTANT:
                # Do NOT label an individual customer PASS/FAIL against the
                # final network target. One customer cannot be expected to
                # solve the whole warehouse. Instead show the MARGINAL benefit
                # of each candidate day and give sales a preferred/fallback.
                if valid_new_days:
                    evaluations = []
                    for candidate_day in valid_new_days:
                        evaluations.append(
                            evaluate_customer_candidate(
                                running_wh_state,
                                customer_id,
                                simulation_route,
                                simulation_carrier,
                                old_day,
                                candidate_day,
                                customer_group,
                                fact,
                                route_day_volume,
                                carrier_day_volume
                            )
                        )

                    candidate_df = (
                        pd.DataFrame(evaluations)
                        .sort_values(
                            ["Ranking Score", "Proposed Delivery Day"],
                            ascending=[False, True]
                        )
                        .reset_index(drop=True)
                    )

                    candidate_df["Negotiation Guidance"] = "Alternative"
                    if len(candidate_df) >= 1:
                        candidate_df.loc[0, "Negotiation Guidance"] = "Preferred"
                    if len(candidate_df) >= 2:
                        candidate_df.loc[1, "Negotiation Guidance"] = "Fallback"

                    # If a candidate worsens the warehouse, call it out rather
                    # than implying it is equally acceptable.
                    candidate_df.loc[
                        candidate_df["Warehouse Contribution"].isin(
                            ["Slightly worsens", "Worsens"]
                        ),
                        "Negotiation Guidance"
                    ] = "Avoid if possible"

                    st.write("**Candidate-day recommendation**")
                    preferred_row = candidate_df.iloc[0]
                    fallback_row = candidate_df.iloc[1] if len(candidate_df) > 1 else None

                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric("Preferred Delivery Day", str(preferred_row["Proposed Delivery Day"]))
                    rc2.metric("Network Fit", str(preferred_row["Network Fit"]))
                    rc3.metric(
                        "Fallback",
                        str(fallback_row["Proposed Delivery Day"]) if fallback_row is not None else "-"
                    )

                    fallback_text = (
                        f" If that does not work, try **{fallback_row['Proposed Delivery Day']}**."
                        if fallback_row is not None else ""
                    )
                    st.info(
                        f"**Preferred: {preferred_row['Proposed Delivery Day']}** — "
                        f"{preferred_row['Network Fit']}. "
                        f"After this move the destination is at "
                        f"**{preferred_row['Destination Carton Share']:.1%}** of the final weekly carton volume, "
                        f"with **{preferred_row['Carton Room to 27%']:,.0f} cartons** of room before the 27% upper limit."
                        + fallback_text
                    )

                    business_candidate_view = candidate_df[[
                        "Negotiation Guidance",
                        "Proposed Delivery Day",
                        "New Pick Day",
                        "Workload Shift",
                        "Network Fit",
                        "Destination Carton Share",
                        "Carton Room to 27%",
                        "Route Impact",
                        "Carrier Impact",
                        "Moved Cartons"
                    ]].copy()

                    business_candidate_view = business_candidate_view.rename(columns={
                        "Destination Carton Share": "Carton % After Move",
                        "Carton Room to 27%": "Room Before 27% (Cartons)"
                    })

                    st.dataframe(
                        business_candidate_view.style.format({
                            "Carton % After Move": "{:.1%}",
                            "Room Before 27% (Cartons)": "{:,.0f}",
                            "Moved Cartons": "{:,.0f}"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

                    recommended_day = preferred_row["Proposed Delivery Day"]
                    default_index = valid_new_days.index(recommended_day)
                else:
                    candidate_df = pd.DataFrame()
                    recommended_day = None
                    default_index = 0

                c1, c2, c3 = st.columns(3)
                with c1:
                    st.write(f"Current Delivery: **{old_day}**")

                with c2:
                    if valid_new_days:
                        new_day = st.selectbox(
                            "Proposed delivery day",
                            valid_new_days,
                            index=default_index,
                            key=f"new_{simulation_route}_{customer_id}"
                        )
                    else:
                        st.error("No valid alternative delivery day.")
                        new_day = None

                new_pick_day = (
                    pick_day_from_delivery(new_day, customer_group)
                    if new_day else None
                )

                with c3:
                    if new_pick_day:
                        st.write(f"New Pick: **{new_pick_day}**")

                if new_day:
                    totals, pick_distribution = get_customer_move_payload(
                        customer_id,
                        simulation_route,
                        old_day,
                        customer_group,
                        planning_fact
                    )

                    running_wh_state = apply_move_to_warehouse_state(
                        running_wh_state,
                        customer_group,
                        pick_distribution,
                        totals,
                        new_pick_day
                    )

                    scenario_rows.append({
                        "Customer ID": customer_id,
                        "Customer Name": customer_name,
                        "Island": IMPACT_ISLAND,
                        "Carrier Name": simulation_carrier,
                        "Route": simulation_route,
                        "Customer Group": customer_group,
                        "Has Billing Volume": customer_has_volume,
                        "# Delivery Days": len(configured_days),
                        "Configured Delivery Days": ", ".join(configured_days),
                        "Historical Route Weight (kg)": total_hist_weight,
                        "Old Day": old_day,
                        "New Day": new_day,
                        "Scheduled Current Pick": scheduled_current_pick,
                        "New Pick Day": new_pick_day,
                        "Moved Gross Weight": totals["Gross Weight"],
                        "Moved Cartons": totals["Cartons"],
                        "Moved Pallet Picks": totals["Pallet Picks"],
                        "Moved Layer Picks": totals["Layer Picks"],
                        "Moved Carton Picks": totals["Carton Picks"],
                        "Moved Keg Picks": totals["Keg Picks"],
                        "Pick Distribution": pick_distribution
                    })

                st.divider()

            if scenario_rows:
                scenario_df = pd.DataFrame(scenario_rows)

                st.subheader("Scenario Setup")
                scenario_view = scenario_df.drop(columns=["Pick Distribution"]).copy()
                st.dataframe(
                    scenario_view.style.format({
                        "# Delivery Days": "{:,.0f}",
                        "Historical Route Weight (kg)": "{:,.0f}",
                        "Moved Gross Weight": "{:,.0f}",
                        "Moved Cartons": "{:,.0f}",
                        "Moved Pallet Picks": "{:,.0f}",
                        "Moved Layer Picks": "{:,.0f}",
                        "Moved Carton Picks": "{:,.0f}",
                        "Moved Keg Picks": "{:,.0f}"
                    }),
                    use_container_width=True,
                    hide_index=True
                )

                run_simulation = st.button(
                    "Run Simulation",
                    type="primary",
                    key="run_selected_simulation"
                )

                if run_simulation:
                    # ==============================================
                    # WAREHOUSE SCENARIO
                    # ==============================================
                    scenario_wh_state = warehouse_base_state.copy()

                    for _, move in scenario_df.iterrows():
                        totals = {
                            "Cartons": move["Moved Cartons"],
                            "Pallet Picks": move["Moved Pallet Picks"],
                            "Layer Picks": move["Moved Layer Picks"],
                            "Carton Picks": move["Moved Carton Picks"],
                            "Keg Picks": move["Moved Keg Picks"]
                        }
                        scenario_wh_state = apply_move_to_warehouse_state(
                            scenario_wh_state,
                            move["Customer Group"],
                            move["Pick Distribution"],
                            totals,
                            move["New Pick Day"]
                        )

                    st.subheader("Warehouse Impact")
                    before_marginal, after_marginal = render_warehouse_comparison(
                        warehouse_base_state,
                        scenario_wh_state,
                        after_label="Scenario"
                    )

                    carton_benefit = (
                        before_marginal["carton_total_deviation_pp"]
                        - after_marginal["carton_total_deviation_pp"]
                    )
                    keg_benefit = (
                        before_marginal["keg_total_deviation_pp"]
                        - after_marginal["keg_total_deviation_pp"]
                    )

                    if carton_benefit > 0 or keg_benefit > 0:
                        st.success(
                            "This selected scenario improves at least one warehouse smoothing measure. "
                            "It does not need to make the entire network perfect to be a useful negotiation scenario."
                        )
                    else:
                        st.warning(
                            "This selected scenario does not improve the combined warehouse shift balance. "
                            "Consider the preferred/fallback recommendations above or use the global optimiser."
                        )

                    # ==============================================
                    # ROUTE IMPACT
                    # ==============================================
                    st.subheader(f"Route Impact - {simulation_route}")

                    route_set = route_days.get(simulation_route, [])
                    route_before = (
                        planning_route_day_volume[
                            planning_route_day_volume["Route"].eq(simulation_route)
                            & planning_route_day_volume["Is_Set_Day"].eq(True)
                        ]
                        .groupby("Delivery Day", observed=True)["Gross Weight"]
                        .sum()
                        .reindex(route_set, fill_value=0.0)
                        .astype(float)
                    )
                    route_after = route_before.copy()

                    for _, move in scenario_df.iterrows():
                        weight = float(move["Moved Gross Weight"])
                        if move["Old Day"] in route_after.index:
                            route_after.loc[move["Old Day"]] = max(
                                0.0,
                                route_after.loc[move["Old Day"]] - weight
                            )
                        if move["New Day"] in route_after.index:
                            route_after.loc[move["New Day"]] += weight

                    route_before_metrics = daily_balance_metrics(route_before.values)
                    route_after_metrics = daily_balance_metrics(route_after.values)

                    route_compare = pd.DataFrame({
                        "Delivery Day": route_set,
                        "Baseline Weight": route_before.values,
                        "Scenario Weight": route_after.values
                    })
                    route_compare["Change"] = (
                        route_compare["Scenario Weight"] - route_compare["Baseline Weight"]
                    )
                    route_compare["Baseline Share"] = (
                        route_compare["Baseline Weight"] / route_compare["Baseline Weight"].sum()
                        if route_compare["Baseline Weight"].sum() > 0 else 0
                    )
                    route_compare["Scenario Share"] = (
                        route_compare["Scenario Weight"] / route_compare["Scenario Weight"].sum()
                        if route_compare["Scenario Weight"].sum() > 0 else 0
                    )

                    r1, r2, r3 = st.columns(3)
                    r1.metric(
                        "Route Peak Share",
                        f"{route_after_metrics['peak_share']:.1%}",
                        f"{(route_after_metrics['peak_share'] - route_before_metrics['peak_share']) * 100:+.2f} pp"
                    )
                    r2.metric(
                        "Route Balance Deviation",
                        f"{route_after_metrics['deviation_pp']:.2f} pp",
                        f"{route_after_metrics['deviation_pp'] - route_before_metrics['deviation_pp']:+.2f} pp"
                    )
                    r3.metric(
                        "Gross Weight Shifted",
                        f"{scenario_df['Moved Gross Weight'].sum():,.0f} kg"
                    )

                    st.dataframe(
                        route_compare.style.format({
                            "Baseline Weight": "{:,.0f}",
                            "Scenario Weight": "{:,.0f}",
                            "Change": "{:+,.0f}",
                            "Baseline Share": "{:.1%}",
                            "Scenario Share": "{:.1%}"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

                    # ==============================================
                    # CARRIER IMPACT
                    # ==============================================
                    st.subheader(f"Carrier Impact - {simulation_carrier}")

                    carrier_before = (
                        planning_carrier_day_volume[
                            planning_carrier_day_volume["Carrier Name"].eq(simulation_carrier)
                        ]
                        .groupby("Delivery Day", observed=True)["Gross Weight"]
                        .sum()
                        .reindex(ROUTE_DAY_ORDER, fill_value=0.0)
                        .astype(float)
                    )
                    carrier_after = carrier_before.copy()

                    for _, move in scenario_df.iterrows():
                        weight = float(move["Moved Gross Weight"])
                        if move["Old Day"] in carrier_after.index:
                            carrier_after.loc[move["Old Day"]] = max(
                                0.0,
                                carrier_after.loc[move["Old Day"]] - weight
                            )
                        if move["New Day"] in carrier_after.index:
                            carrier_after.loc[move["New Day"]] += weight

                    carrier_before_metrics = daily_balance_metrics(carrier_before.values)
                    carrier_after_metrics = daily_balance_metrics(carrier_after.values)

                    carrier_compare = pd.DataFrame({
                        "Delivery Day": ROUTE_DAY_ORDER,
                        "Baseline Weight": carrier_before.values,
                        "Scenario Weight": carrier_after.values
                    })
                    carrier_compare["Change"] = (
                        carrier_compare["Scenario Weight"] - carrier_compare["Baseline Weight"]
                    )
                    carrier_compare["Baseline Share"] = (
                        carrier_compare["Baseline Weight"] / carrier_compare["Baseline Weight"].sum()
                        if carrier_compare["Baseline Weight"].sum() > 0 else 0
                    )
                    carrier_compare["Scenario Share"] = (
                        carrier_compare["Scenario Weight"] / carrier_compare["Scenario Weight"].sum()
                        if carrier_compare["Scenario Weight"].sum() > 0 else 0
                    )

                    c1, c2 = st.columns(2)
                    c1.metric(
                        "Carrier Peak Share",
                        f"{carrier_after_metrics['peak_share']:.1%}",
                        f"{(carrier_after_metrics['peak_share'] - carrier_before_metrics['peak_share']) * 100:+.2f} pp"
                    )
                    c2.metric(
                        "Carrier Balance Deviation",
                        f"{carrier_after_metrics['deviation_pp']:.2f} pp",
                        f"{carrier_after_metrics['deviation_pp'] - carrier_before_metrics['deviation_pp']:+.2f} pp"
                    )

                    st.dataframe(
                        carrier_compare.style.format({
                            "Baseline Weight": "{:,.0f}",
                            "Scenario Weight": "{:,.0f}",
                            "Change": "{:+,.0f}",
                            "Baseline Share": "{:.1%}",
                            "Scenario Share": "{:.1%}"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

                    st.info(
                        "Use the combined warehouse, route and carrier sections together for the judgement call. "
                        "The individual scenario is assessed by whether it improves the current network, not by requiring one customer to achieve the final 23%-27% target."
                    )
