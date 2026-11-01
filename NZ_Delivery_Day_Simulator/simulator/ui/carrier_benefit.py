"""Streamlit UI for carrier benefit."""

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

def render_carrier_benefit():

    st.header("Carrier Benefit - North Island")
    st.caption(
        "Before = today. After = the optimiser's recommended days (Tab 3). "
        "Per-week averages. One run = a route on one delivery date; one drop = one customer on one delivery date."
    )

    cb_plan = st.session_state.get("latest_global_assignment")
    if not isinstance(cb_plan, pd.DataFrame) or cb_plan.empty:
        st.info("Run the **Global Optimisation** in Tab 3 first. This tab shows the result of that plan.")
    else:
        cb_drops, cb_customer_days, cb_weeks = carrier_benefit_base(planning_fact, delivery_day)
        cb_carriers = sorted(cb_plan["Carrier Name"].dropna().unique().tolist())

        def cb_kpis(table):
            """Before / After totals and ratios for a slice of the route-day table."""
            def side(sfx):
                runs, drops = table[f"Runs {sfx}"].sum(), table[f"Drops {sfx}"].sum()
                kg, kegs = table[f"Gross Weight {sfx}"].sum(), table[f"Keg Qty {sfx}"].sum()
                return {"Runs / week": runs, "Drops / week": drops,
                        "Drops per run": drops / runs if runs else 0.0,
                        "Kg per run": kg / runs if runs else 0.0,
                        "Kegs per run": kegs / runs if runs else 0.0,
                        "Gross weight / week": kg, "Kegs / week": kegs}
            return side("Before"), side("After")

        def cb_kpi_row(table):
            b, a = cb_kpis(table)
            cols = st.columns(5)
            cols[0].metric("Runs / week", f"{a['Runs / week']:,.1f}",
                           f"{a['Runs / week'] - b['Runs / week']:+,.1f} vs {b['Runs / week']:,.1f}",
                           delta_color="inverse")
            cols[1].metric("Drops / week", f"{a['Drops / week']:,.1f}",
                           f"{a['Drops / week'] - b['Drops / week']:+,.1f} vs {b['Drops / week']:,.1f}",
                           delta_color="inverse")
            cols[2].metric("Drops per run", f"{a['Drops per run']:,.1f}",
                           f"{a['Drops per run'] - b['Drops per run']:+,.1f} vs {b['Drops per run']:,.1f}")
            cols[3].metric("Kg per run", f"{a['Kg per run']:,.0f}",
                           f"{a['Kg per run'] - b['Kg per run']:+,.0f} vs {b['Kg per run']:,.0f}")
            cols[4].metric("Kegs per run", f"{a['Kegs per run']:,.1f}",
                           f"{a['Kegs per run'] - b['Kegs per run']:+,.1f} vs {b['Kegs per run']:,.1f}")
            return b, a

        def cb_charts(table, title):
            """Before vs After by weekday: runs, gross weight, kegs."""
            by_day = (table.groupby("Delivery Day", observed=True)[
                [f"{c} {s}" for c in CB_COLUMNS for s in ["Before", "After"]]].sum()
                .reindex(ROUTE_DAY_ORDER, fill_value=0.0).reset_index())
            charts = [("Runs", "Runs per week", ".1f"),
                      ("Gross Weight", "Gross weight per week (kg)", ",.0f"),
                      ("Keg Qty", "Kegs per week", ",.0f")]
            cols = st.columns(3)
            for col, (measure, label, fmt) in zip(cols, charts):
                long = by_day.melt(id_vars="Delivery Day",
                                   value_vars=[f"{measure} Before", f"{measure} After"],
                                   var_name="Scenario", value_name=label)
                long["Scenario"] = long["Scenario"].str.replace(f"{measure} ", "", regex=False)
                fig = px.bar(long, x="Delivery Day", y=label, color="Scenario", barmode="group",
                             text_auto=fmt, title=f"{title} - {label}",
                             color_discrete_map={"Before": "#9CA3AF", "After": "#0068C9"})
                fig.update_layout(legend_title_text="", margin=dict(t=50, l=10, r=10, b=10))
                col.plotly_chart(fig, use_container_width=True)
            return by_day

        cb_carrier = st.selectbox("Carrier", cb_carriers, key="cb_carrier")
        cb_table, cb_moves = carrier_benefit_route_days(
            cb_drops, cb_customer_days, cb_weeks, cb_plan, carrier=cb_carrier
        )

        if cb_table.empty:
            st.info("No planning volume for this carrier.")
        else:
            # ---------------- carrier level ----------------
            st.subheader(cb_carrier)
            cb_b, cb_a = cb_kpi_row(cb_table)
            cb_by_day = cb_charts(cb_table, cb_carrier)

            # ---------------- route summary ----------------
            desc = planning_route_master.drop_duplicates("Route").set_index("Route")["Route Description"]
            route_rows = []
            for route, rt in cb_table.groupby("Route", observed=True):
                rb, ra = cb_kpis(rt)
                route_rows.append({
                    "Route": route, "Route Description": desc.get(route, ""),
                    "Runs Before": rb["Runs / week"], "Runs After": ra["Runs / week"],
                    "Drops Before": rb["Drops / week"], "Drops After": ra["Drops / week"],
                    "Drops/Run Before": rb["Drops per run"], "Drops/Run After": ra["Drops per run"],
                    "Kg/Run Before": rb["Kg per run"], "Kg/Run After": ra["Kg per run"],
                    "Kegs/Run Before": rb["Kegs per run"], "Kegs/Run After": ra["Kegs per run"],
                })
            route_tbl = pd.DataFrame(route_rows)
            route_tbl["Runs Saved"] = route_tbl["Runs Before"] - route_tbl["Runs After"]
            route_tbl = route_tbl.sort_values(["Runs Saved", "Route"], ascending=[False, True])

            st.subheader("Routes (per week)")
            st.dataframe(
                route_tbl.style.format({
                    **{c: "{:,.1f}" for c in route_tbl.columns if c.startswith(("Runs", "Drops", "Kegs"))},
                    **{c: "{:,.0f}" for c in route_tbl.columns if c.startswith("Kg")},
                }),
                use_container_width=True, hide_index=True
            )

            # ---------------- route drill-down ----------------
            st.divider()
            route_labels = {
                r: f"{r} - {d}" if d else r
                for r, d in zip(route_tbl["Route"], route_tbl["Route Description"])
            }
            cb_route = st.selectbox(
                "Drill down: route", list(route_labels.keys()),
                format_func=lambda r: route_labels.get(r, r), key="cb_route"
            )
            route_table = cb_table[cb_table["Route"].eq(cb_route)]
            st.subheader(route_labels.get(cb_route, cb_route))
            st.caption(f"Route delivery days: {', '.join(route_days.get(cb_route, [])) or '-'}")
            cb_kpi_row(route_table)
            route_by_day = cb_charts(route_table, cb_route)

            route_moves = cb_moves[cb_moves["Route"].eq(cb_route)] if not cb_moves.empty else cb_moves
            st.write("**Customer moves on this route**")
            if route_moves.empty:
                st.caption("No impacted customers on this route.")
            else:
                names = planning_fact.drop_duplicates("Customer ID").set_index("Customer ID")["Customer Name"]
                rm = route_moves.copy()
                rm.insert(1, "Customer Name", rm["Customer ID"].map(names))
                outcome_counts = rm["Outcome"].value_counts()
                st.caption(" | ".join(f"{k}: {v}" for k, v in outcome_counts.items()))
                st.dataframe(
                    rm.drop(columns=["Route"]).style.format({
                        "Drops / wk": "{:,.2f}", "Gross Weight / wk": "{:,.0f}", "Keg Qty / wk": "{:,.1f}"
                    }),
                    use_container_width=True, hide_index=True
                )

            # ---------------- Excel pack ----------------
            import io
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as xw:
                pd.DataFrame([{"Measure": k, "Before": cb_b[k], "After": cb_a[k], "Change": cb_a[k] - cb_b[k]}
                              for k in cb_b]).to_excel(xw, sheet_name="Carrier summary", index=False)
                cb_by_day.to_excel(xw, sheet_name="Carrier by day", index=False)
                route_tbl.to_excel(xw, sheet_name="Routes", index=False)
                cb_table.sort_values(["Route", "Delivery Day"]).to_excel(xw, sheet_name="Route by day", index=False)
                cb_moves.to_excel(xw, sheet_name="Customer moves", index=False)
            st.download_button(
                "Download carrier pack (Excel)",
                data=buf.getvalue(),
                file_name=f"carrier_benefit_{str(cb_carrier).replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="cb_download"
            )
            st.caption(f"Basis: {cb_weeks:.0f} weeks of history; planning population "
                       "(current Customer + Route + Delivery Day); optimiser plan from Tab 3.")
