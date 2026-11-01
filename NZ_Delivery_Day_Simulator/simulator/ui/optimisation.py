"""Streamlit UI for optimisation."""

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

def render_optimisation():

    st.header("Global Warehouse Optimisation - North Island")

    st.subheader("Warehouse")
    st.write("**Volume Smoothing**")
    st.write("Total Cartons across the four future warehouse shifts. Target: 25% each; acceptable range: 23%-27%.")
    st.write("**Pick Method Smoothing**")
    st.write("Pallet, Layer, Carton and Keg workloads are smoothed across the same four shifts, with equal priority after Total Cartons.")
    st.info(
        "Planning keeps the historical workload of customers that still exist in the current Delivery Day master. "
        "Historical-only customers that are no longer in the current master remain in Tab 1 but are excluded from future planning."
    )
    st.write("**Carrier Smoothing**")
    st.write("After warehouse smoothing, the optimiser also tries to make each carrier's Gross Weight and Keg Qty distribution as even as possible across the delivery days that carrier can operate.")

    if pulp is None:
        st.error(
            "Global optimisation requires PuLP. Add `pulp` to requirements.txt and install it with `pip install pulp`."
        )
    else:
        scope_option = st.radio(
            "Optimisation scope",
            ["All North Island impacted customers", "Selected carrier only"],
            horizontal=True,
            key="global_scope"
        )

        if scope_option == "Selected carrier only":
            global_carrier = st.selectbox(
                "Carrier",
                sorted(impacted_customer_master["Carrier Name"].dropna().unique().tolist()),
                key="global_carrier"
            )
            global_population = impacted_customer_master[
                impacted_customer_master["Carrier Name"].eq(global_carrier)
            ].copy()
        else:
            global_carrier = None
            global_population = impacted_customer_master.copy()

        st.write(
            f"Population: **{global_population['Customer ID'].nunique():,} customers** across "
            f"**{global_population['Route'].nunique():,} routes**."
        )

        with st.expander("Planning population reconciliation", expanded=False):
            st.write(
                "Planning rows require an exact current Customer ID + Route + Delivery Day match. "
                "Warehouse optimisation then derives the planning pick day from that current setting; "
                "historical PickDate_Adjusted is retained only for descriptive analysis."
            )
            st.dataframe(
                planning_population_reconciliation.style.format({
                    "Customers": "{:,.0f}",
                    "Cartons": "{:,.0f}",
                    "Gross Weight": "{:,.0f}"
                }),
                use_container_width=True,
                hide_index=True
            )

            if not excluded_planning_fact.empty:
                exclusion_summary = (
                    excluded_planning_fact
                    .groupby("Planning Population Status", observed=True)
                    .agg(
                        Rows=("Customer ID", "size"),
                        Customers=("Customer ID", "nunique"),
                        Cartons=("Cartons", "sum"),
                        Gross_Weight=("Gross Weight", "sum")
                    )
                    .reset_index()
                    .rename(columns={"Gross_Weight": "Gross Weight"})
                )
                st.dataframe(
                    exclusion_summary.style.format({
                        "Rows": "{:,.0f}",
                        "Customers": "{:,.0f}",
                        "Cartons": "{:,.0f}",
                        "Gross Weight": "{:,.0f}"
                    }),
                    use_container_width=True,
                    hide_index=True
                )

        with st.expander("Impact flag reconciliation", expanded=False):
            impact_flag_view = impact_flag_reconciliation.copy()
            impact_flag_view["Business Rule Impacted"] = impact_flag_view["Business Rule Impacted"].map({
                True: "Yes", False: "No"
            })
            impact_flag_view["Excel_Impact_Flag"] = impact_flag_view["Excel_Impact_Flag"].map({
                True: "Yes", False: "No"
            })
            impact_flag_view = impact_flag_view.rename(columns={
                "Excel_Impact_Flag": "Excel Impact Flag"
            })
            st.dataframe(
                impact_flag_view.style.format({
                    "Customers": "{:,.0f}",
                    "Routes": "{:,.0f}"
                }),
                use_container_width=True,
                hide_index=True
            )

        force_plan_generation = st.session_state.pop(
            "force_generate_negotiation_plan", False
        )
        run_global = st.button(
            "Run Global Optimisation",
            type="primary",
            key="run_global_optimisation"
        ) or force_plan_generation

        if force_plan_generation:
            st.info("Generating the sales negotiation plan from the global optimiser...")

        if run_global:
            # ==================================================
            # BUILD OPTIMISATION UNITS
            # One unit = one impacted Customer ID + Route.
            # ==================================================
            units = []
            excluded_no_candidate = []
            excluded_unknown_group = []

            for _, master_row in global_population.drop_duplicates(
                subset=["Customer ID", "Route"]
            ).iterrows():
                customer_id = int(master_row["Customer ID"])
                route = master_row["Route"]
                carrier = master_row["Carrier Name"]
                group = master_row["Customer Group"]

                if group not in CUSTOMER_GROUPS:
                    excluded_unknown_group.append({
                        "Customer ID": customer_id,
                        "Customer Name": master_row["Customer Name"],
                        "Carrier Name": carrier,
                        "Route": route,
                        "Customer Group": group,
                        "Reason": "Unknown customer group"
                    })
                    continue

                # The removed day is determined by the business rule, not by
                # the Excel impact flag.
                old_day = IMPACTED_DELIVERY_DAY_BY_GROUP[group]

                # Historical workload on the exact current Customer + Route +
                # Delivery Day setting. This is the workload that must leave
                # the removed Shift 5.
                totals, pick_distribution = get_customer_move_payload(
                    customer_id,
                    route,
                    old_day,
                    group,
                    planning_fact
                )

                # Valid candidate = route operates that day AND it is one of the
                # group's future delivery days (Metro Mon-Thu, Regional Tue-Fri).
                candidates = [
                    d for d in route_days.get(route, [])
                    if d != old_day and delivery_day_is_allowed(d, group)
                ]

                if not candidates:
                    excluded_no_candidate.append({
                        "Customer ID": customer_id,
                        "Customer Name": master_row["Customer Name"],
                        "Carrier Name": carrier,
                        "Route": route,
                        "Customer Group": group,
                        "Current Delivery Day": old_day,
                        "Route Delivery Days": ", ".join(route_days.get(route, [])),
                        "Moved Cartons": totals.get("Cartons", 0.0),
                        "Moved Keg Picks": totals.get("Keg Picks", 0.0),
                        "Moved Gross Weight": totals.get("Gross Weight", 0.0),
                        "Reason": "No valid alternative route day"
                    })
                    continue

                units.append({
                    "Customer ID": customer_id,
                    "Customer Name": master_row["Customer Name"],
                    "Route": route,
                    "Carrier Name": carrier,
                    "Customer Group": group,
                    "Old Day": old_day,
                    "Candidates": candidates,
                    "Totals": totals,
                    "Pick Distribution": pick_distribution
                })

            if not units:
                st.warning("No optimisation units with valid alternative delivery days were found.")
            else:
                u1, u2, u3 = st.columns(3)
                u1.metric("Customers Optimised", f"{len(units):,}")
                u2.metric("No Valid Alternative", f"{len(excluded_no_candidate):,}")
                u3.metric("Unknown Customer Group", f"{len(excluded_unknown_group):,}")

                if excluded_no_candidate:
                    with st.expander("Customers excluded because their route has no valid alternative day for their group"):
                        no_candidate_df = pd.DataFrame(excluded_no_candidate)
                        st.dataframe(
                            no_candidate_df.style.format({
                                "Moved Cartons": "{:,.0f}",
                                "Moved Keg Picks": "{:,.0f}",
                                "Moved Gross Weight": "{:,.0f}"
                            }),
                            use_container_width=True,
                            hide_index=True
                        )

                if excluded_unknown_group:
                    with st.expander("Customers excluded because Customer Group is not Metro/Regional"):
                        st.dataframe(
                            pd.DataFrame(excluded_unknown_group),
                            use_container_width=True,
                            hide_index=True
                        )

                # ==================================================
                # FIXED STATE = current physical warehouse minus the
                # volume of every customer the optimiser will re-assign.
                # ==================================================
                baseline_state = build_warehouse_state(planning_warehouse_all)

                # ==================================================
                # REMOVED SHIFT RECONCILIATION
                # Shift 5 = Metro Thursday PLANNING pick + Regional Friday
                # PLANNING pick. These pick days are derived from the current
                # Delivery Day setting, not from historical PickDate_Adjusted.
                # Therefore Metro Friday + Regional Monday impacted settings
                # should reconcile exactly to Shift 5. Any remainder is a true
                # route-setting / data-quality exception.
                # ==================================================
                shift5_current_cartons = shift_measure_value(
                    baseline_state, "Shift 5", "Cartons", future_only=False
                )
                shift5_current_kegs = shift_measure_value(
                    baseline_state, "Shift 5", "Keg Picks", future_only=False
                )

                movable_shift5_cartons = float(sum(
                    unit["Totals"].get("Cartons", 0.0) for unit in units
                ))
                movable_shift5_kegs = float(sum(
                    unit["Totals"].get("Keg Picks", 0.0) for unit in units
                ))

                shift5_exception_cartons = max(
                    0.0, shift5_current_cartons - movable_shift5_cartons
                )
                shift5_exception_kegs = max(
                    0.0, shift5_current_kegs - movable_shift5_kegs
                )

                st.subheader("Removed Shift Reconciliation")
                shift5_recon = pd.DataFrame([
                    {
                        "Measure": "Total Cartons",
                        "Current Shift 5": shift5_current_cartons,
                        "Movable by Optimiser": movable_shift5_cartons,
                        "Requires Resolution": shift5_exception_cartons
                    },
                    {
                        "Measure": "Keg Picks",
                        "Current Shift 5": shift5_current_kegs,
                        "Movable by Optimiser": movable_shift5_kegs,
                        "Requires Resolution": shift5_exception_kegs
                    }
                ])
                st.dataframe(
                    shift5_recon.style.format({
                        "Current Shift 5": "{:,.0f}",
                        "Movable by Optimiser": "{:,.0f}",
                        "Requires Resolution": "{:,.0f}"
                    }),
                    use_container_width=True,
                    hide_index=True
                )

                if shift5_exception_cartons > 0.01 or shift5_exception_kegs > 0.01:
                    st.warning(
                        "Some Shift 5 workload cannot currently be reassigned by the optimiser. "
                        "The remaining amount is treated as exception volume and is shown in the "
                        "customer exception lists below."
                    )
                else:
                    st.success(
                        "All current Shift 5 workload is represented by movable optimisation units. "
                        "The optimised Shift 5 should therefore reduce to zero."
                    )

                fixed = {
                    (row["Customer Group"], row["Pick Day"]): {
                        m: float(row[m]) for m in WAREHOUSE_MEASURES
                    }
                    for _, row in baseline_state.iterrows()
                }

                for unit in units:
                    for _, pick_row in unit["Pick Distribution"].iterrows():
                        key = (unit["Customer Group"], pick_row["Pick Day"])
                        if key not in fixed:
                            continue
                        for m in WAREHOUSE_MEASURES:
                            fixed[key][m] = max(
                                0.0, fixed[key][m] - float(pick_row.get(m, 0.0))
                            )

                def fixed_value(group, pick_day, measure):
                    return fixed.get((group, pick_day), {}).get(measure, 0.0)

                # ==================================================
                # OPTIMISATION MODEL
                # ==================================================
                model = pulp.LpProblem(
                    "Delivery_Day_Shift_Smoothing",
                    pulp.LpMinimize
                )

                x = {}
                for i, unit in enumerate(units):
                    for j, day in enumerate(unit["Candidates"]):
                        x[(i, day)] = pulp.LpVariable(f"x_{i}_{j}", cat="Binary")

                # Hard rule: each impacted customer gets exactly one valid new day.
                for i, unit in enumerate(units):
                    model += (
                        pulp.lpSum(x[(i, day)] for day in unit["Candidates"]) == 1,
                        f"AssignOnce_{i}"
                    )

                def group_day_expression(group, pick_day, measure):
                    expr = fixed_value(group, pick_day, measure)
                    for i, unit in enumerate(units):
                        if unit["Customer Group"] != group:
                            continue
                        amount = float(unit["Totals"].get(measure, 0.0))
                        if amount == 0:
                            continue
                        for day in unit["Candidates"]:
                            if pick_day_from_delivery(day, group) == pick_day:
                                expr += amount * x[(i, day)]
                    return expr

                def shift_expression(shift, measure):
                    return pulp.lpSum(
                        group_day_expression(group, pick_day, measure)
                        for group, pick_day in FUTURE_SHIFT_MAP[shift].items()
                    )

                objective_terms = []

                # Total Cartons first; Pallet, Layer, Carton Pick and Keg equal after it.
                measure_settings = [
                    ("Cartons", "cartons", 1000.0, 100.0, 300.0),
                    ("Pallet Picks", "pallet", 250.0, 25.0, 75.0),
                    ("Layer Picks", "layer", 250.0, 25.0, 75.0),
                    ("Carton Picks", "cartonpick", 250.0, 25.0, 75.0),
                    ("Keg Picks", "keg", 250.0, 25.0, 75.0)
                ]

                for measure, tag, w_max, w_sum, w_band in measure_settings:
                    # Target is based on the full CURRENT five-shift weekly workload.
                    # The optimiser redistributes Shift 5 into Shifts 1-4; it must not
                    # shrink the denominator by hiding the removed shift.
                    total = current_five_shift_total(baseline_state, measure)

                    if total <= 0:
                        continue

                    target = GROUP_TARGET_SHARE * total
                    lower = GROUP_MIN_SHARE * total
                    upper = GROUP_MAX_SHARE * total

                    max_dev = pulp.LpVariable(f"maxdev_{tag}", lowBound=0)
                    dev_terms = []
                    band_terms = []

                    for shift in FUTURE_SHIFT_ORDER:
                        expr = shift_expression(shift, measure)

                        pos = pulp.LpVariable(f"dev_pos_{tag}_{shift.replace(' ', '_')}", lowBound=0)
                        neg = pulp.LpVariable(f"dev_neg_{tag}_{shift.replace(' ', '_')}", lowBound=0)
                        model += pos >= expr - target
                        model += neg >= target - expr
                        model += max_dev >= expr - target
                        model += max_dev >= target - expr
                        dev_terms.extend([pos, neg])

                        b_low = pulp.LpVariable(f"band_low_{tag}_{shift.replace(' ', '_')}", lowBound=0)
                        b_high = pulp.LpVariable(f"band_high_{tag}_{shift.replace(' ', '_')}", lowBound=0)
                        model += b_low >= lower - expr
                        model += b_high >= expr - upper
                        band_terms.extend([b_low, b_high])

                    objective_terms.append((w_max / total) * max_dev)
                    objective_terms.append((w_sum / total) * pulp.lpSum(dev_terms))
                    objective_terms.append((w_band / total) * pulp.lpSum(band_terms))

                # ==================================================
                # SECONDARY CARRIER SMOOTHING
                # Warehouse smoothing remains the primary objective.
                # Carrier Gross Weight and Keg Qty are then smoothed across
                # the delivery days the carrier can actually operate.
                # ==================================================
                carrier_names_in_scope = sorted({
                    unit["Carrier Name"] for unit in units
                    if pd.notna(unit["Carrier Name"])
                })

                # Carrier service days = union of configured route days for
                # routes belonging to that carrier. This avoids penalising a
                # carrier for a weekday it cannot operate.
                carrier_service_days = {}
                for carrier_name in carrier_names_in_scope:
                    carrier_routes = (
                        planning_route_master.loc[
                            planning_route_master["Carrier Name"].eq(carrier_name),
                            "Route"
                        ]
                        .dropna()
                        .astype(str)
                        .unique()
                        .tolist()
                    )
                    days = []
                    for r in carrier_routes:
                        days.extend(route_days.get(r, []))
                    carrier_service_days[carrier_name] = [
                        d for d in ROUTE_DAY_ORDER if d in set(days)
                    ]

                # Start from the current active planning carrier/day volumes,
                # then remove the affected customer volume. The binary decision
                # variables add that volume back to the chosen new day.
                carrier_fixed = {}
                for carrier_name in carrier_names_in_scope:
                    base_rows = planning_carrier_day_volume[
                        planning_carrier_day_volume["Carrier Name"].eq(carrier_name)
                    ]
                    for day in ROUTE_DAY_ORDER:
                        row = base_rows[base_rows["Delivery Day"].eq(day)]
                        carrier_fixed[(carrier_name, day, "Gross Weight")] = (
                            float(row["Gross Weight"].sum()) if not row.empty else 0.0
                        )
                        carrier_fixed[(carrier_name, day, "Keg Qty")] = (
                            float(row["Keg Qty"].sum()) if not row.empty else 0.0
                        )

                for unit in units:
                    carrier_name = unit["Carrier Name"]
                    old_day = unit["Old Day"]
                    if carrier_name not in carrier_names_in_scope:
                        continue
                    carrier_fixed[(carrier_name, old_day, "Gross Weight")] = max(
                        0.0,
                        carrier_fixed.get((carrier_name, old_day, "Gross Weight"), 0.0)
                        - float(unit["Totals"].get("Gross Weight", 0.0))
                    )
                    carrier_fixed[(carrier_name, old_day, "Keg Qty")] = max(
                        0.0,
                        carrier_fixed.get((carrier_name, old_day, "Keg Qty"), 0.0)
                        - float(unit["Totals"].get("Keg Qty", 0.0))
                    )

                def carrier_day_expression(carrier_name, delivery_day_name, measure):
                    expr = carrier_fixed.get((carrier_name, delivery_day_name, measure), 0.0)
                    for i, unit in enumerate(units):
                        if unit["Carrier Name"] != carrier_name:
                            continue
                        amount = float(unit["Totals"].get(measure, 0.0))
                        if amount == 0:
                            continue
                        for candidate_day in unit["Candidates"]:
                            if candidate_day == delivery_day_name:
                                expr += amount * x[(i, candidate_day)]
                    return expr

                # Keep carrier terms deliberately below the warehouse terms.
                # Gross Weight and Keg Qty have equal priority to each other.
                carrier_count = max(1, len(carrier_names_in_scope))
                for carrier_idx, carrier_name in enumerate(carrier_names_in_scope):
                    service_days = carrier_service_days.get(carrier_name, [])
                    if len(service_days) <= 1:
                        continue

                    for measure, tag in [("Gross Weight", "gw"), ("Keg Qty", "kegqty")]:
                        total = sum(
                            carrier_fixed.get((carrier_name, d, measure), 0.0)
                            for d in ROUTE_DAY_ORDER
                        ) + sum(
                            float(unit["Totals"].get(measure, 0.0))
                            for unit in units
                            if unit["Carrier Name"] == carrier_name
                        )
                        if total <= 0:
                            continue

                        target = total / len(service_days)
                        max_dev = pulp.LpVariable(
                            f"carrier_maxdev_{tag}_{carrier_idx}", lowBound=0
                        )
                        dev_terms = []
                        for day_idx, day in enumerate(service_days):
                            expr = carrier_day_expression(carrier_name, day, measure)
                            pos = pulp.LpVariable(
                                f"carrier_dev_pos_{tag}_{carrier_idx}_{day_idx}", lowBound=0
                            )
                            neg = pulp.LpVariable(
                                f"carrier_dev_neg_{tag}_{carrier_idx}_{day_idx}", lowBound=0
                            )
                            model += pos >= expr - target
                            model += neg >= target - expr
                            model += max_dev >= expr - target
                            model += max_dev >= target - expr
                            dev_terms.extend([pos, neg])

                        # Normalised and averaged across carriers so transport
                        # smoothing cannot overpower warehouse smoothing.
                        objective_terms.append((20.0 / carrier_count / total) * max_dev)
                        objective_terms.append(
                            (5.0 / carrier_count / total) * pulp.lpSum(dev_terms)
                        )

                # ==================================================
                # BUSIEST-DAY CAP - ROUTE AND CARRIER
                # Moving a customer must not make a route's or carrier's
                # busiest delivery day heavier than it is today (Gross Weight).
                #   new day weight <= current peak day weight
                # Implemented with a slack variable carrying a very large
                # penalty: it behaves as a hard rule whenever a feasible
                # assignment exists, but never makes the model infeasible.
                # Any remaining breach is reported in "Busiest-Day Check".
                # ==================================================
                PEAK_BREACH_PENALTY = 10000.0

                # ---- Route ----
                route_base_rows = planning_route_day_volume[
                    planning_route_day_volume["Is_Set_Day"].eq(True)
                ]
                routes_in_scope = sorted({str(unit["Route"]) for unit in units})
                route_fixed = {}
                route_peak = {}
                for route_name in routes_in_scope:
                    rows = route_base_rows[route_base_rows["Route"].eq(route_name)]
                    by_day = rows.groupby("Delivery Day", observed=True)["Gross Weight"].sum()
                    for day in ROUTE_DAY_ORDER:
                        route_fixed[(route_name, day)] = float(by_day.get(day, 0.0))
                    route_peak[route_name] = float(by_day.max()) if not by_day.empty else 0.0

                for unit in units:
                    key = (str(unit["Route"]), unit["Old Day"])
                    route_fixed[key] = max(
                        0.0,
                        route_fixed.get(key, 0.0) - float(unit["Totals"].get("Gross Weight", 0.0))
                    )

                for route_idx, route_name in enumerate(routes_in_scope):
                    peak = route_peak.get(route_name, 0.0)
                    if peak <= 0:
                        continue
                    route_units = [
                        (i, unit) for i, unit in enumerate(units)
                        if str(unit["Route"]) == route_name
                    ]
                    candidate_days = sorted(
                        {d for _, unit in route_units for d in unit["Candidates"]},
                        key=lambda d: DAY_IDX.get(d, 999)
                    )
                    for day in candidate_days:
                        expr = route_fixed.get((route_name, day), 0.0)
                        for i, unit in route_units:
                            if day in unit["Candidates"]:
                                expr += float(unit["Totals"].get("Gross Weight", 0.0)) * x[(i, day)]
                        slack = pulp.LpVariable(
                            f"route_peak_slack_{route_idx}_{DAY_IDX.get(day, 9)}", lowBound=0
                        )
                        model += expr <= peak + slack
                        objective_terms.append((PEAK_BREACH_PENALTY / peak) * slack)

                # ---- Carrier ----
                for carrier_idx, carrier_name in enumerate(carrier_names_in_scope):
                    base_rows = planning_carrier_day_volume[
                        planning_carrier_day_volume["Carrier Name"].eq(carrier_name)
                    ]
                    by_day = base_rows.groupby("Delivery Day", observed=True)["Gross Weight"].sum()
                    peak = float(by_day.max()) if not by_day.empty else 0.0
                    if peak <= 0:
                        continue
                    for day in carrier_service_days.get(carrier_name, []):
                        expr = carrier_day_expression(carrier_name, day, "Gross Weight")
                        slack = pulp.LpVariable(
                            f"carrier_peak_slack_{carrier_idx}_{DAY_IDX.get(day, 9)}", lowBound=0
                        )
                        model += expr <= peak + slack
                        objective_terms.append((PEAK_BREACH_PENALTY / peak) * slack)

                model += pulp.lpSum(objective_terms)

                solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=120)  # seconds
                model.solve(solver)
                solver_status = pulp.LpStatus.get(model.status, str(model.status))

                # sol_status: 1 = optimal, 2 = feasible (time limit hit with a solution).
                sol_status = getattr(model, "sol_status", None)
                has_solution = sol_status in (1, 2) or (
                    sol_status is None and solver_status == "Optimal"
                )

                if sol_status == 2:
                    st.write("Solver status: **Feasible (time limit reached, best solution found)**")
                else:
                    st.write(f"Solver status: **{solver_status}**")

                if not has_solution:
                    st.error(
                        "The solver did not return a usable solution. All smoothing and pick-mix rules are soft, "
                        "so this usually means the time limit was reached before any solution was found. "
                        "Try the 'Selected carrier only' scope."
                    )
                else:
                    # ==================================================
                    # BUILD ASSIGNMENTS + OPTIMISED WAREHOUSE STATE
                    # ==================================================
                    assignments = []
                    optimised_state = baseline_state.copy()

                    for i, unit in enumerate(units):
                        chosen_day = max(
                            unit["Candidates"],
                            key=lambda d: float(pulp.value(x[(i, d)]) or 0.0)
                        )
                        new_pick_day = pick_day_from_delivery(
                            chosen_day,
                            unit["Customer Group"]
                        )

                        optimised_state = apply_move_to_warehouse_state(
                            optimised_state,
                            unit["Customer Group"],
                            unit["Pick Distribution"],
                            unit["Totals"],
                            new_pick_day
                        )

                        assignments.append({
                            "Customer ID": unit["Customer ID"],
                            "Customer Name": unit["Customer Name"],
                            "Carrier Name": unit["Carrier Name"],
                            "Route": unit["Route"],
                            "Customer Group": unit["Customer Group"],
                            "Old Delivery Day": unit["Old Day"],
                            "Recommended Delivery Day": chosen_day,
                            "New Pick Day": new_pick_day,
                            "Other Valid Days": ", ".join(
                                d for d in unit["Candidates"] if d != chosen_day
                            ),
                            "Moved Cartons": unit["Totals"]["Cartons"],
                            "Moved Pallet Picks": unit["Totals"]["Pallet Picks"],
                            "Moved Layer Picks": unit["Totals"]["Layer Picks"],
                            "Moved Carton Picks": unit["Totals"]["Carton Picks"],
                            "Moved Keg Picks": unit["Totals"]["Keg Picks"],
                            "Moved Keg Qty": unit["Totals"].get("Keg Qty", 0.0),
                            "Moved Gross Weight": unit["Totals"]["Gross Weight"],
                            "Moved Keg Gross Weight": unit["Totals"].get("Keg Gross Weight", 0.0),
                            "Moved Carton Gross Weight": unit["Totals"].get("Carton Gross Weight", 0.0)
                        })

                    assignment_df = pd.DataFrame(assignments)

                    # Save the latest theoretical optimum.
                    # IMPORTANT: Streamlit reruns the whole script whenever a selector changes.
                    # Persist everything required to redraw the result without re-running CBC.
                    st.session_state["latest_global_assignment"] = assignment_df.copy()
                    st.session_state["latest_global_optimised_state"] = optimised_state.copy()
                    st.session_state["latest_global_baseline_state"] = baseline_state.copy()
                    st.session_state["latest_global_solver_status"] = (
                        "Feasible (time limit reached, best solution found)"
                        if sol_status == 2 else solver_status
                    )
                    st.session_state["latest_global_excluded_no_candidate"] = excluded_no_candidate.copy()
                    st.session_state["latest_global_excluded_unknown_group"] = excluded_unknown_group.copy()
                    st.session_state["latest_global_shift5_reconciliation"] = shift5_recon.copy()
                    st.session_state["latest_global_shift5_exception_cartons"] = shift5_exception_cartons
                    st.session_state["latest_global_shift5_exception_kegs"] = shift5_exception_kegs
                    st.session_state["latest_global_scope_signature"] = (
                        scope_option,
                        global_carrier if global_carrier is not None else "ALL"
                    )
                    st.session_state["global_result_ready"] = True

                    st.success(
                        "Optimisation complete. The result is saved for this session, so you can now "
                        "change the carrier and route selectors without running the optimiser again."
                    )

        # ==========================================================
        # DISPLAY SAVED GLOBAL OPTIMISATION RESULT
        # ==========================================================
        # This section is deliberately OUTSIDE `if run_global:`.
        # Changing Carrier / Route reruns Streamlit, but the saved solver result remains visible.
        current_scope_signature = (
            scope_option,
            global_carrier if global_carrier is not None else "ALL"
        )
        saved_scope_signature = st.session_state.get("latest_global_scope_signature")
        result_ready = st.session_state.get("global_result_ready", False)

        if result_ready and saved_scope_signature != current_scope_signature:
            st.info(
                "The optimisation scope has changed. Click **Run Global Optimisation** to create a new result "
                "for the selected scope."
            )
        elif result_ready:
            assignment_df = st.session_state["latest_global_assignment"].copy()
            optimised_state = st.session_state["latest_global_optimised_state"].copy()
            baseline_state = st.session_state["latest_global_baseline_state"].copy()

            saved_solver_status = st.session_state.get("latest_global_solver_status", "")
            if saved_solver_status:
                st.write(f"Solver status: **{saved_solver_status}**")

            st.subheader("Optimised Warehouse Result")
            shift5_exception_cartons_saved = float(
                st.session_state.get("latest_global_shift5_exception_cartons", 0.0)
            )
            shift5_exception_kegs_saved = float(
                st.session_state.get("latest_global_shift5_exception_kegs", 0.0)
            )

            if shift5_exception_cartons_saved <= 0.01 and shift5_exception_kegs_saved <= 0.01:
                st.info(
                    "Shift 5 is the removed workload. All of its current workload is movable, so the "
                    "optimised Shift 5 should be zero while Shifts 1-4 move toward 25% each."
                )
            else:
                st.info(
                    "Shift 5 is the removed workload. The optimiser moves every customer that has a "
                    "valid alternative route day. Any Shift 5 volume that remains is exception volume "
                    "requiring route / customer resolution, not an intended future workload."
                )

            _, final_metrics = render_warehouse_comparison(
                baseline_state,
                optimised_state,
                after_label="Optimised"
            )

            optimised_shift5_cartons = shift_measure_value(
                optimised_state, "Shift 5", "Cartons", future_only=False
            )
            optimised_shift5_kegs = shift_measure_value(
                optimised_state, "Shift 5", "Keg Picks", future_only=False
            )

            if shift5_exception_cartons_saved <= 0.01 and shift5_exception_kegs_saved <= 0.01:
                if abs(optimised_shift5_cartons) > 0.01 or abs(optimised_shift5_kegs) > 0.01:
                    st.error(
                        "Shift 5 should be fully removed, but workload remains after optimisation. "
                        "Check the movement reconciliation before using this result."
                    )
                else:
                    st.success("Shift 5 fully removed in the optimised result.")
            elif optimised_shift5_cartons > 0.01 or optimised_shift5_kegs > 0.01:
                st.warning(
                    f"Shift 5 still contains {optimised_shift5_cartons:,.0f} cartons and "
                    f"{optimised_shift5_kegs:,.0f} keg picks. This is exception workload that "
                    "could not be assigned to a valid alternative route day."
                )

            # Reconciliation: optimisation moves workload; it must not create or lose it.
            recon_rows = []
            for measure in WAREHOUSE_MEASURES:
                current_total = current_five_shift_total(baseline_state, measure)
                optimised_total = current_five_shift_total(optimised_state, measure)
                difference = optimised_total - current_total
                recon_rows.append({
                    "Measure": MEASURE_LABELS[measure],
                    "Current Total": current_total,
                    "Optimised Total": optimised_total,
                    "Difference": difference,
                    "Check": "PASS" if abs(difference) <= 0.01 else "CHECK"
                })

            reconciliation = pd.DataFrame(recon_rows)
            st.write("**Warehouse Reconciliation**")
            st.dataframe(
                reconciliation.style.format({
                    "Current Total": "{:,.0f}",
                    "Optimised Total": "{:,.0f}",
                    "Difference": "{:+,.0f}"
                }),
                use_container_width=True,
                hide_index=True
            )

            # Optimised totals: simple business-facing warehouse summary.
            opt_detail = five_shift_detail(optimised_state)
            st.write("**Optimised Warehouse Total Cartons and Pick Methods**")
            opt_view = opt_detail[[
                "Workload Shift",
                "Total Cartons", "Total Cartons Share",
                "Pallet Picks", "Pallet Picks Share",
                "Layer Picks", "Layer Picks Share",
                "Carton Picks", "Carton Picks Share",
                "Keg Picks", "Keg Picks Share"
            ]].copy()
            st.dataframe(
                opt_view.style.format({
                    "Total Cartons": "{:,.0f}", "Total Cartons Share": "{:.1%}",
                    "Pallet Picks": "{:,.0f}", "Pallet Picks Share": "{:.1%}",
                    "Layer Picks": "{:,.0f}", "Layer Picks Share": "{:.1%}",
                    "Carton Picks": "{:,.0f}", "Carton Picks Share": "{:.1%}",
                    "Keg Picks": "{:,.0f}", "Keg Picks Share": "{:.1%}"
                }),
                use_container_width=True,
                hide_index=True
            )

            all_breaches = (
                final_metrics["carton_band_breaches"]
                + final_metrics["pallet_band_breaches"]
                + final_metrics["layer_band_breaches"]
                + final_metrics["carton_pick_band_breaches"]
                + final_metrics["keg_band_breaches"]
            )
            if all_breaches == 0:
                st.success("All four future warehouse shifts are within 23%-27% for every workload measure.")
            else:
                st.warning("This is the smoothest achievable profile with the available route-day choices.")

            # ==================================================
            # CUSTOMER RECOMMENDATIONS
            # ==================================================
            st.subheader("Recommended Customer Delivery-Day Changes")

            if assignment_df.empty:
                st.info("No assignments were returned.")
            else:
                customer_plan_view = assignment_df[[
                    "Customer ID",
                    "Customer Name",
                    "Carrier Name",
                    "Route",
                    "Old Delivery Day",
                    "Recommended Delivery Day",
                    "Other Valid Days",
                    "Moved Cartons"
                ]].copy()

                customer_plan_view = customer_plan_view.rename(columns={
                    "Old Delivery Day": "Current Day",
                    "Recommended Delivery Day": "Recommended Day",
                    "Other Valid Days": "Other Available Days"
                })

                st.dataframe(
                    customer_plan_view.style.format({"Moved Cartons": "{:,.0f}"}),
                    use_container_width=True,
                    hide_index=True
                )

            # ==================================================
            # TRANSPORT IMPACT - SELECT CARRIER / ROUTE
            # ==================================================
            st.subheader("Transport Impact")

            transport_cols = [
                "Carrier Name", "Route", "Delivery Day",
                "Gross Weight", "Carton Gross Weight", "Keg Gross Weight", "Keg Qty"
            ]
            route_transport = (
                planning_route_day_volume[
                    planning_route_day_volume["Is_Set_Day"].eq(True)
                ][transport_cols]
                .copy()
                .rename(columns={
                    "Gross Weight": "Current Gross Weight",
                    "Carton Gross Weight": "Current Carton Gross Weight",
                    "Keg Gross Weight": "Current Keg Gross Weight",
                    "Keg Qty": "Current Keg Qty"
                })
            )
            route_transport["Optimised Gross Weight"] = route_transport["Current Gross Weight"]
            route_transport["Optimised Carton Gross Weight"] = route_transport["Current Carton Gross Weight"]
            route_transport["Optimised Keg Gross Weight"] = route_transport["Current Keg Gross Weight"]
            route_transport["Optimised Keg Qty"] = route_transport["Current Keg Qty"]

            movement_pairs = [
                ("Moved Gross Weight", "Optimised Gross Weight"),
                ("Moved Carton Gross Weight", "Optimised Carton Gross Weight"),
                ("Moved Keg Gross Weight", "Optimised Keg Gross Weight"),
                ("Moved Keg Qty", "Optimised Keg Qty")
            ]

            for _, move in assignment_df.iterrows():
                old_mask = (
                    route_transport["Route"].eq(move["Route"])
                    & route_transport["Delivery Day"].eq(move["Old Delivery Day"])
                )
                new_mask = (
                    route_transport["Route"].eq(move["Route"])
                    & route_transport["Delivery Day"].eq(move["Recommended Delivery Day"])
                )
                for moved_col, scenario_col in movement_pairs:
                    amount = float(move.get(moved_col, 0.0))
                    route_transport.loc[old_mask, scenario_col] -= amount
                    route_transport.loc[new_mask, scenario_col] += amount

            scenario_cols = [c for _, c in movement_pairs]
            route_transport[scenario_cols] = route_transport[scenario_cols].clip(lower=0)

            # ==================================================
            # BUSIEST-DAY CHECK (route + carrier peak must not increase)
            # ==================================================
            def peak_check_rows(frame, level, name_col):
                rows = []
                for name, grp in frame.groupby(name_col, observed=True):
                    by_day = grp.groupby("Delivery Day", observed=True)[
                        ["Current Gross Weight", "Optimised Gross Weight"]
                    ].sum()
                    if by_day.empty or by_day["Current Gross Weight"].max() <= 0:
                        continue
                    cur_day = by_day["Current Gross Weight"].idxmax()
                    opt_day = by_day["Optimised Gross Weight"].idxmax()
                    cur_peak = float(by_day["Current Gross Weight"].max())
                    opt_peak = float(by_day["Optimised Gross Weight"].max())
                    rows.append({
                        "Level": level,
                        "Name": name,
                        "Current Busiest Day": cur_day,
                        "Current Peak (kg)": cur_peak,
                        "Optimised Busiest Day": opt_day,
                        "Optimised Peak (kg)": opt_peak,
                        "Peak Change (kg)": opt_peak - cur_peak,
                        "Status": "OK" if opt_peak <= cur_peak + 0.5 else "Peak increased"
                    })
                return rows

            moved_routes = set(assignment_df["Route"].astype(str)) if not assignment_df.empty else set()
            moved_carriers = set(assignment_df["Carrier Name"].dropna()) if not assignment_df.empty else set()
            peak_check = pd.DataFrame(
                peak_check_rows(
                    route_transport[route_transport["Carrier Name"].isin(moved_carriers)],
                    "Carrier", "Carrier Name"
                )
                + peak_check_rows(
                    route_transport[route_transport["Route"].astype(str).isin(moved_routes)],
                    "Route", "Route"
                )
            )

            st.write("**Busiest-Day Check - Route and Carrier**")
            st.caption(
                "Rule: moving customers must not make any route's or carrier's busiest delivery day "
                "heavier than it is today (Gross Weight)."
            )
            if peak_check.empty:
                st.info("No route or carrier volume to check.")
            else:
                breaches = peak_check[peak_check["Status"].ne("OK")]
                if breaches.empty:
                    st.success(
                        f"All {len(peak_check):,} affected routes and carriers keep their busiest day "
                        "at or below today's peak."
                    )
                else:
                    st.error(
                        f"{len(breaches):,} route(s)/carrier(s) exceed today's peak because no valid "
                        "alternative day had enough room. Review these with transport."
                    )
                st.dataframe(
                    peak_check.sort_values(["Status", "Peak Change (kg)"], ascending=[False, False])
                    .style.format({
                        "Current Peak (kg)": "{:,.0f}",
                        "Optimised Peak (kg)": "{:,.0f}",
                        "Peak Change (kg)": "{:+,.0f}"
                    }),
                    use_container_width=True,
                    hide_index=True
                )

            transport_carriers = sorted(
                route_transport["Carrier Name"].dropna().unique().tolist()
            )
            selected_impact_carrier = st.selectbox(
                "Select carrier to review",
                transport_carriers,
                key="optimised_transport_carrier"
            )

            previous_impact_carrier = st.session_state.get(
                "_last_optimised_transport_carrier"
            )
            if previous_impact_carrier != selected_impact_carrier:
                st.session_state["_last_optimised_transport_carrier"] = selected_impact_carrier
                st.session_state.pop("optimised_transport_route", None)

            carrier_impact = (
                route_transport[
                    route_transport["Carrier Name"].eq(selected_impact_carrier)
                ]
                .groupby("Delivery Day", observed=True)[[
                    "Current Gross Weight", "Optimised Gross Weight",
                    "Current Carton Gross Weight", "Optimised Carton Gross Weight",
                    "Current Keg Gross Weight", "Optimised Keg Gross Weight",
                    "Current Keg Qty", "Optimised Keg Qty"
                ]]
                .sum()
                .reindex(ROUTE_DAY_ORDER, fill_value=0.0)
                .reset_index()
            )

            # Carrier smoothing KPIs. Lower peak share / spread means the
            # carrier workload is more evenly distributed across weekdays.
            current_weight_metrics = daily_balance_metrics(
                carrier_impact["Current Gross Weight"].values
            )
            optimised_weight_metrics = daily_balance_metrics(
                carrier_impact["Optimised Gross Weight"].values
            )
            current_keg_metrics = daily_balance_metrics(
                carrier_impact["Current Keg Qty"].values
            )
            optimised_keg_metrics = daily_balance_metrics(
                carrier_impact["Optimised Keg Qty"].values
            )

            c1, c2, c3, c4 = st.columns(4)
            c1.metric(
                "Busiest Weight Day",
                f"{optimised_weight_metrics['peak_share']:.1%}",
                f"{(optimised_weight_metrics['peak_share'] - current_weight_metrics['peak_share']) * 100:+.2f} pp"
            )
            c2.metric(
                "Weight Daily Spread",
                f"{optimised_weight_metrics['spread_share'] * 100:.2f} pp",
                f"{(optimised_weight_metrics['spread_share'] - current_weight_metrics['spread_share']) * 100:+.2f} pp"
            )
            c3.metric(
                "Busiest Keg Day",
                f"{optimised_keg_metrics['peak_share']:.1%}",
                f"{(optimised_keg_metrics['peak_share'] - current_keg_metrics['peak_share']) * 100:+.2f} pp"
            )
            c4.metric(
                "Keg Qty Daily Spread",
                f"{optimised_keg_metrics['spread_share'] * 100:.2f} pp",
                f"{(optimised_keg_metrics['spread_share'] - current_keg_metrics['spread_share']) * 100:+.2f} pp"
            )

            carrier_weight_long = carrier_impact[[
                "Delivery Day", "Current Gross Weight", "Optimised Gross Weight"
            ]].melt(
                id_vars="Delivery Day",
                var_name="Position",
                value_name="Gross Weight"
            )
            carrier_weight_long["Position"] = carrier_weight_long["Position"].str.replace(
                " Gross Weight", "", regex=False
            )
            fig_carrier_impact = px.bar(
                carrier_weight_long,
                x="Delivery Day",
                y="Gross Weight",
                color="Position",
                barmode="group",
                title=f"{selected_impact_carrier} - Current vs Optimised Gross Weight"
            )
            fig_carrier_impact.update_yaxes(tickformat=",")
            st.plotly_chart(fig_carrier_impact, use_container_width=True)

            carrier_keg_long = carrier_impact[[
                "Delivery Day", "Current Keg Qty", "Optimised Keg Qty"
            ]].melt(
                id_vars="Delivery Day",
                var_name="Position",
                value_name="Keg Qty"
            )
            carrier_keg_long["Position"] = carrier_keg_long["Position"].str.replace(
                " Keg Qty", "", regex=False
            )
            fig_carrier_keg = px.bar(
                carrier_keg_long,
                x="Delivery Day",
                y="Keg Qty",
                color="Position",
                barmode="group",
                title=f"{selected_impact_carrier} - Current vs Optimised Keg Qty"
            )
            fig_carrier_keg.update_yaxes(tickformat=",")
            st.plotly_chart(fig_carrier_keg, use_container_width=True)

            carrier_view = carrier_impact.copy()
            current_weight_total = carrier_view["Current Gross Weight"].sum()
            optimised_weight_total = carrier_view["Optimised Gross Weight"].sum()
            current_keg_total = carrier_view["Current Keg Qty"].sum()
            optimised_keg_total = carrier_view["Optimised Keg Qty"].sum()
            carrier_view["Current Weight %"] = np.where(
                current_weight_total > 0,
                carrier_view["Current Gross Weight"] / current_weight_total,
                0.0
            )
            carrier_view["Optimised Weight %"] = np.where(
                optimised_weight_total > 0,
                carrier_view["Optimised Gross Weight"] / optimised_weight_total,
                0.0
            )
            carrier_view["Current Keg %"] = np.where(
                current_keg_total > 0,
                carrier_view["Current Keg Qty"] / current_keg_total,
                0.0
            )
            carrier_view["Optimised Keg %"] = np.where(
                optimised_keg_total > 0,
                carrier_view["Optimised Keg Qty"] / optimised_keg_total,
                0.0
            )

            st.dataframe(
                carrier_view[[
                    "Delivery Day",
                    "Current Gross Weight", "Current Weight %",
                    "Optimised Gross Weight", "Optimised Weight %",
                    "Current Keg Qty", "Current Keg %",
                    "Optimised Keg Qty", "Optimised Keg %"
                ]].style.format({
                    "Current Gross Weight": "{:,.0f}",
                    "Current Weight %": "{:.1%}",
                    "Optimised Gross Weight": "{:,.0f}",
                    "Optimised Weight %": "{:.1%}",
                    "Current Keg Qty": "{:,.0f}",
                    "Current Keg %": "{:.1%}",
                    "Optimised Keg Qty": "{:,.0f}",
                    "Optimised Keg %": "{:.1%}"
                }),
                use_container_width=True,
                hide_index=True
            )

            carrier_routes_available = sorted(
                route_transport.loc[
                    route_transport["Carrier Name"].eq(selected_impact_carrier),
                    "Route"
                ].dropna().unique().tolist()
            )
            selected_impact_route = st.selectbox(
                "Select route to review",
                carrier_routes_available,
                key="optimised_transport_route"
            )

            route_impact = (
                route_transport[route_transport["Route"].eq(selected_impact_route)][[
                    "Delivery Day",
                    "Current Gross Weight", "Optimised Gross Weight",
                    "Current Carton Gross Weight", "Optimised Carton Gross Weight",
                    "Current Keg Gross Weight", "Optimised Keg Gross Weight",
                    "Current Keg Qty", "Optimised Keg Qty"
                ]]
                .set_index("Delivery Day")
                .reindex(ROUTE_DAY_ORDER)
                .fillna(0.0)
                .reset_index()
            )

            route_weight_long = route_impact[[
                "Delivery Day", "Current Gross Weight", "Optimised Gross Weight"
            ]].melt(
                id_vars="Delivery Day",
                var_name="Position",
                value_name="Gross Weight"
            )
            route_weight_long["Position"] = route_weight_long["Position"].str.replace(
                " Gross Weight", "", regex=False
            )
            fig_route_impact = px.bar(
                route_weight_long,
                x="Delivery Day",
                y="Gross Weight",
                color="Position",
                barmode="group",
                title=f"{selected_impact_route} - Current vs Optimised Gross Weight"
            )
            fig_route_impact.update_yaxes(tickformat=",")
            st.plotly_chart(fig_route_impact, use_container_width=True)

            route_keg_long = route_impact[[
                "Delivery Day", "Current Keg Qty", "Optimised Keg Qty"
            ]].melt(
                id_vars="Delivery Day",
                var_name="Position",
                value_name="Keg Qty"
            )
            route_keg_long["Position"] = route_keg_long["Position"].str.replace(
                " Keg Qty", "", regex=False
            )
            fig_route_keg = px.bar(
                route_keg_long,
                x="Delivery Day",
                y="Keg Qty",
                color="Position",
                barmode="group",
                title=f"{selected_impact_route} - Current vs Optimised Keg Qty"
            )
            fig_route_keg.update_yaxes(tickformat=",")
            st.plotly_chart(fig_route_keg, use_container_width=True)

            st.dataframe(
                route_impact.style.format({
                    "Current Gross Weight": "{:,.0f}",
                    "Optimised Gross Weight": "{:,.0f}",
                    "Current Carton Gross Weight": "{:,.0f}",
                    "Optimised Carton Gross Weight": "{:,.0f}",
                    "Current Keg Gross Weight": "{:,.0f}",
                    "Optimised Keg Gross Weight": "{:,.0f}",
                    "Current Keg Qty": "{:,.0f}",
                    "Optimised Keg Qty": "{:,.0f}"
                }),
                use_container_width=True,
                hide_index=True
            )
