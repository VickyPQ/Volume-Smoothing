"""Streamlit UI for negotiation."""

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

def render_negotiation():

    st.header("Sales Negotiation Plan - North Island")

    latest_assignment = st.session_state.get("latest_global_assignment")

    if latest_assignment is None or latest_assignment.empty:
        st.info(
            "No negotiation plan has been generated in this session yet. You do not need to go to Tab 3 first. "
            "Click below and the global optimiser will generate the starting plan automatically."
        )
        if st.button(
            "Generate Negotiation Plan",
            type="primary",
            key="generate_plan_from_tab5"
        ):
            st.session_state["force_generate_negotiation_plan"] = True
            st.rerun()

    else:
        tracker_key = "negotiation_tracker_df"

        signature = tuple(
            latest_assignment[["Customer ID", "Route", "Recommended Delivery Day"]]
            .astype(str)
            .agg("|".join, axis=1)
            .tolist()
        )
        old_signature = st.session_state.get("negotiation_assignment_signature")

        if tracker_key not in st.session_state or signature != old_signature:
            tracker = latest_assignment.copy()
            tracker["Negotiation Status"] = "Pending"
            tracker["Agreed Delivery Day"] = tracker["Recommended Delivery Day"]
            tracker["Sales Note"] = ""
            st.session_state[tracker_key] = tracker
            st.session_state["negotiation_assignment_signature"] = signature

        tracker = st.session_state[tracker_key].copy()

        st.info(
            "**Fast workflow:** filter to the customers you are working on, then use **Accept all visible recommendations**. "
            "Only edit individual rows when the customer agrees to a different valid delivery day. "
            "Pending = still negotiating; Accepted = customer has confirmed the agreed day."
        )

        # ======================================================
        # FILTERS - make this an exception-management view
        # ======================================================
        f1, f2, f3, f4 = st.columns(4)
        carrier_filter = f1.multiselect(
            "Carrier",
            sorted(tracker["Carrier Name"].dropna().unique().tolist()),
            key="neg_carrier_filter_v2"
        )

        route_options = tracker.copy()
        if carrier_filter:
            route_options = route_options[route_options["Carrier Name"].isin(carrier_filter)]
        route_filter = f2.multiselect(
            "Route",
            sorted(route_options["Route"].dropna().unique().tolist()),
            key="neg_route_filter_v2"
        )

        recommended_filter = f3.multiselect(
            "Recommended day",
            ROUTE_DAY_ORDER,
            key="neg_recommended_day_filter_v2"
        )

        status_filter = f4.multiselect(
            "Status",
            ["Pending", "Accepted"],
            default=["Pending"],
            key="neg_status_filter_v2"
        )

        edit_view = tracker.copy()
        if carrier_filter:
            edit_view = edit_view[edit_view["Carrier Name"].isin(carrier_filter)]
        if route_filter:
            edit_view = edit_view[edit_view["Route"].isin(route_filter)]
        if recommended_filter:
            edit_view = edit_view[edit_view["Recommended Delivery Day"].isin(recommended_filter)]
        if status_filter:
            edit_view = edit_view[edit_view["Negotiation Status"].isin(status_filter)]

        st.write(
            f"Showing **{len(edit_view):,} customers** from **{len(tracker):,}** in the negotiation plan."
        )

        # ======================================================
        # BULK ACTIONS
        # ======================================================
        b1, b2, b3 = st.columns([1.4, 1.2, 2.4])

        if b1.button(
            "Accept all visible recommendations",
            type="primary",
            disabled=edit_view.empty,
            key="bulk_accept_visible"
        ):
            updated = tracker.copy()
            keys = set(
                zip(
                    edit_view["Customer ID"].astype(str),
                    edit_view["Route"].astype(str)
                )
            )
            mask = updated.apply(
                lambda r: (str(r["Customer ID"]), str(r["Route"])) in keys,
                axis=1
            )
            updated.loc[mask, "Negotiation Status"] = "Accepted"
            updated.loc[mask, "Agreed Delivery Day"] = updated.loc[
                mask, "Recommended Delivery Day"
            ]
            st.session_state[tracker_key] = updated
            st.success(f"Accepted {int(mask.sum()):,} visible customer recommendations.")
            st.rerun()

        if b2.button(
            "Set visible back to Pending",
            disabled=edit_view.empty,
            key="bulk_pending_visible"
        ):
            updated = tracker.copy()
            keys = set(
                zip(
                    edit_view["Customer ID"].astype(str),
                    edit_view["Route"].astype(str)
                )
            )
            mask = updated.apply(
                lambda r: (str(r["Customer ID"]), str(r["Route"])) in keys,
                axis=1
            )
            updated.loc[mask, "Negotiation Status"] = "Pending"
            st.session_state[tracker_key] = updated
            st.success(f"Returned {int(mask.sum()):,} visible customers to Pending.")
            st.rerun()


        # ======================================================
        # INDIVIDUAL EXCEPTIONS
        # ======================================================
        with st.expander("Individual customer exceptions", expanded=False):

            editor_columns = [
                "Customer ID",
                "Customer Name",
                "Carrier Name",
                "Route",
                "Customer Group",
                "Old Delivery Day",
                "Recommended Delivery Day",
                "Negotiation Status",
                "Agreed Delivery Day",
                "Sales Note"
            ]

            edited = st.data_editor(
                edit_view[editor_columns],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config={
                    "Negotiation Status": st.column_config.SelectboxColumn(
                        "Negotiation Status",
                        options=["Pending", "Accepted"],
                        required=True
                    ),
                    "Agreed Delivery Day": st.column_config.SelectboxColumn(
                        "Agreed Delivery Day",
                        options=ROUTE_DAY_ORDER,
                        required=True
                    ),
                    "Sales Note": st.column_config.TextColumn("Sales Note")
                },
                disabled=[
                    "Customer ID", "Customer Name", "Carrier Name", "Route",
                    "Customer Group", "Old Delivery Day", "Recommended Delivery Day"
                ],
                key="negotiation_editor_v2"
            )

            if st.button(
                "Save Individual Exceptions",
                type="primary",
                key="save_negotiation_v2"
            ):
                updated_tracker = tracker.copy()

                for _, erow in edited.iterrows():
                    mask = (
                        updated_tracker["Customer ID"].eq(erow["Customer ID"])
                        & updated_tracker["Route"].eq(erow["Route"])
                    )
                    updated_tracker.loc[mask, "Negotiation Status"] = erow["Negotiation Status"]
                    updated_tracker.loc[mask, "Agreed Delivery Day"] = erow["Agreed Delivery Day"]
                    updated_tracker.loc[mask, "Sales Note"] = erow["Sales Note"]

                invalid = []
                for _, row in updated_tracker.iterrows():
                    if row["Negotiation Status"] != "Accepted":
                        continue

                    agreed_day = row["Agreed Delivery Day"]
                    valid_days = route_days.get(row["Route"], [])
                    if (
                        agreed_day not in valid_days
                        or not delivery_day_is_allowed(agreed_day, row["Customer Group"])
                    ):
                        invalid.append(
                            f"{row['Customer ID']} - {row['Customer Name']}: "
                            f"{agreed_day} is not valid for route {row['Route']}."
                        )

                if invalid:
                    st.error(
                        "Some accepted decisions are invalid:\n\n"
                        + "\n".join(invalid[:20])
                    )
                else:
                    st.session_state[tracker_key] = updated_tracker
                    st.success("Individual exceptions saved.")
                    st.rerun()

        tracker = st.session_state[tracker_key].copy()

        # ======================================================
        # SALES PROGRESS + CONFIRMED NETWORK POSITION
        # ======================================================
        status_counts = tracker["Negotiation Status"].value_counts()
        accepted_count = int(status_counts.get("Accepted", 0))
        pending_count = int(status_counts.get("Pending", 0))

        confirmed = tracker[tracker["Negotiation Status"].eq("Accepted")].copy()
        baseline_state = build_warehouse_state(planning_warehouse_all)
        confirmed_state = baseline_state.copy()

        for _, row in confirmed.iterrows():
            customer_id = int(row["Customer ID"])
            route = row["Route"]
            group = row["Customer Group"]
            old_day = row["Old Delivery Day"]
            agreed_day = row["Agreed Delivery Day"]
            new_pick = pick_day_from_delivery(agreed_day, group)

            totals, pick_distribution = get_customer_move_payload(
                customer_id, route, old_day, group, planning_fact
            )
            confirmed_state = apply_move_to_warehouse_state(
                confirmed_state,
                group,
                pick_distribution,
                totals,
                new_pick
            )

        total_moved_cartons = float(pd.to_numeric(tracker["Moved Cartons"], errors="coerce").fillna(0).sum())
        confirmed_moved_cartons = float(pd.to_numeric(confirmed["Moved Cartons"], errors="coerce").fillna(0).sum())
        volume_confirmed = safe_divide(confirmed_moved_cartons, total_moved_cartons)

        baseline_metrics = warehouse_metrics(baseline_state)
        confirmed_metrics = warehouse_metrics(confirmed_state)
        optimum_state = st.session_state.get("latest_global_optimised_state")

        if isinstance(optimum_state, pd.DataFrame) and not optimum_state.empty:
            optimum_metrics = warehouse_metrics(optimum_state)
            carton_progress = balance_progress(
                baseline_metrics["carton_total_deviation_pp"],
                confirmed_metrics["carton_total_deviation_pp"],
                optimum_metrics["carton_total_deviation_pp"]
            )
            secondary_progress_values = []
            for metric_name in [
                "pallet_total_deviation_pp",
                "layer_total_deviation_pp",
                "carton_pick_total_deviation_pp",
                "keg_total_deviation_pp"
            ]:
                secondary_progress_values.append(
                    balance_progress(
                        baseline_metrics[metric_name],
                        confirmed_metrics[metric_name],
                        optimum_metrics[metric_name]
                    )
                )
            pick_workload_progress = sum(secondary_progress_values) / len(secondary_progress_values)
        else:
            carton_progress = None
            pick_workload_progress = None

        p1, p2, p3, p4 = st.columns(4)
        p1.metric(
            "Customers Confirmed",
            f"{accepted_count:,} / {len(tracker):,}"
        )
        p2.metric(
            "Carton Volume Confirmed",
            f"{volume_confirmed:.1%}"
        )
        p3.metric(
            "Carton Balance Progress",
            f"{carton_progress:.0%}" if carton_progress is not None else "Run Optimiser"
        )
        p4.metric(
            "Pick Workload Progress",
            f"{pick_workload_progress:.0%}" if pick_workload_progress is not None else "Run Optimiser"
        )

        st.subheader("Confirmed Network Capacity")
        st.info(
            "**Network position:** Can take more = the shift still has carton capacity; "
            "Within range = 23%-27%; Too much volume = choose another valid day where possible."
        )

        capacity_view = negotiation_capacity_table(confirmed_state)
        st.dataframe(
            capacity_view.style.format({
                "Confirmed Cartons": "{:,.0f}",
                "Confirmed Carton %": "{:.1%}",
                "Room Before 27%": "{:,.0f}"
            }),
            use_container_width=True,
            hide_index=True
        )

        c1, c2 = st.columns(2)
        c1.metric(
            "Carton Shifts Within Range",
            f"{int((capacity_view['Network Position'] == 'Within range').sum()):,} / {len(capacity_view):,}"
        )
        c2.metric(
            "Pending Customers",
            f"{pending_count:,}"
        )

        # ======================================================
        # NEXT-BEST SALES QUEUE - PENDING ONLY
        # ======================================================
        unresolved = tracker[tracker["Negotiation Status"].eq("Pending")].copy()

        st.subheader("Next-Best Sales Queue")

        if unresolved.empty:
            st.success("All customers in the plan have been accepted.")
        else:
            max_to_evaluate = st.slider(
                "Pending customers to evaluate",
                min_value=1,
                max_value=max(1, min(100, len(unresolved))),
                value=min(25, len(unresolved)),
                key="neg_eval_count_v2"
            )

            if st.button(
                "Refresh Next-Best Sales Queue",
                key="recalc_neg_guidance_v2"
            ):
                guidance_rows = []
                unresolved_eval = unresolved.sort_values(
                    "Moved Cartons", ascending=False
                ).head(max_to_evaluate)

                for _, row in unresolved_eval.iterrows():
                    customer_id = int(row["Customer ID"])
                    route = row["Route"]
                    carrier = row["Carrier Name"]
                    group = row["Customer Group"]
                    old_day = row["Old Delivery Day"]

                    candidates = [
                        day for day in route_days.get(route, [])
                        if day != old_day
                        and delivery_day_is_allowed(day, group)
                    ]

                    evals = [
                        evaluate_customer_candidate(
                            confirmed_state,
                            customer_id,
                            route,
                            carrier,
                            old_day,
                            day,
                            group,
                            planning_fact,
                            planning_route_day_volume,
                            planning_carrier_day_volume
                        )
                        for day in candidates
                    ]

                    if not evals:
                        continue

                    eval_df = pd.DataFrame(evals).sort_values(
                        "Ranking Score", ascending=False
                    ).reset_index(drop=True)
                    best = eval_df.iloc[0]
                    fallback = eval_df.iloc[1] if len(eval_df) > 1 else None

                    guidance_rows.append({
                        "Customer ID": customer_id,
                        "Customer Name": row["Customer Name"],
                        "Carrier Name": carrier,
                        "Route": route,
                        "Preferred Day Now": best["Proposed Delivery Day"],
                        "Fallback Day": fallback["Proposed Delivery Day"] if fallback is not None else "",
                        "Network Fit": best["Network Fit"],
                        "Carton % After Move": best["Destination Carton Share"],
                        "Room Before 27%": best["Carton Room to 27%"],
                        "Moved Cartons": best["Moved Cartons"],
                        "_score": best["Ranking Score"]
                    })

                guidance_df = pd.DataFrame(guidance_rows)

                if guidance_df.empty:
                    st.info("No valid alternatives were found for the Pending customers evaluated.")
                else:
                    guidance_df = guidance_df.sort_values(
                        ["_score", "Moved Cartons"],
                        ascending=[False, False]
                    ).drop(columns=["_score"])

                    guidance_df.insert(
                        0,
                        "Priority",
                        range(1, len(guidance_df) + 1)
                    )

                    sales_queue_view = guidance_df[[
                        "Priority",
                        "Customer ID",
                        "Customer Name",
                        "Carrier Name",
                        "Route",
                        "Preferred Day Now",
                        "Fallback Day",
                        "Network Fit",
                        "Carton % After Move",
                        "Room Before 27%",
                        "Moved Cartons"
                    ]].copy()
                    sales_queue_view = sales_queue_view.rename(columns={
                        "Preferred Day Now": "Preferred Day",
                        "Room Before 27%": "Room Before 27% (Cartons)"
                    })
                    st.dataframe(
                        sales_queue_view.style.format({
                            "Priority": "{:,.0f}",
                            "Carton % After Move": "{:.1%}",
                            "Room Before 27% (Cartons)": "{:,.0f}",
                            "Moved Cartons": "{:,.0f}"
                        }),
                        use_container_width=True,
                        hide_index=True
                    )

                    st.info(
                        "**Network Fit** is the practical guardrail: Can take more = extra volume still fits; "
                        "Within range = destination stays inside 23%-27%; Over range = use another valid day where possible."
                    )
