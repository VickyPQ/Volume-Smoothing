"""Shared Streamlit presentation helpers."""

import streamlit as st

from simulator.config import *  # noqa: F403
from simulator.simulation import *  # noqa: F403

# ==========================================================

SHIFT_FORMAT = {
    "Current Total Cartons": "{:,.0f}",
    "Optimised Total Cartons": "{:,.0f}",
    "Scenario Total Cartons": "{:,.0f}",
    "Confirmed Total Cartons": "{:,.0f}",
}


def smoothing_compare_table(before_state, after_state, after_label="Scenario"):
    before = five_shift_detail(before_state)
    after = five_shift_detail(after_state)

    keys = [
        "Workload Shift",
        "Metro Pick Day",
        "Regional Pick Day",
        "Metro Delivery Day",
        "Regional Delivery Day"
    ]

    before_cols = keys.copy()
    after_cols = keys.copy()
    for label in MEASURE_LABELS.values():
        before_cols += [label, f"{label} Share"]
        after_cols += [label, f"{label} Share", f"{label} Status"]

    before = before[before_cols].copy()
    after = after[after_cols].copy()

    before = before.rename(columns={
        **{label: f"Current {label}" for label in MEASURE_LABELS.values()},
        **{f"{label} Share": f"Current {label} %" for label in MEASURE_LABELS.values()}
    })
    after = after.rename(columns={
        **{label: f"{after_label} {label}" for label in MEASURE_LABELS.values()},
        **{f"{label} Share": f"{after_label} {label} %" for label in MEASURE_LABELS.values()},
        **{f"{label} Status": f"{label} Status" for label in MEASURE_LABELS.values()}
    })

    return before.merge(after, on=keys, how="left")


def pick_mix_compare_table(before_state, after_state):
    return smoothing_compare_table(before_state, after_state)


def render_warehouse_comparison(before_state, after_state, after_label="Scenario"):
    before_m = warehouse_metrics(before_state)
    after_m = warehouse_metrics(after_state)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Carton Shifts in Range", f"{4 - after_m['carton_band_breaches']:,} / 4")
    k2.metric("Pallet Shifts in Range", f"{4 - after_m['pallet_band_breaches']:,} / 4")
    k3.metric("Layer Shifts in Range", f"{4 - after_m['layer_band_breaches']:,} / 4")
    k4.metric("Carton Pick Shifts in Range", f"{4 - after_m['carton_pick_band_breaches']:,} / 4")
    k5.metric("Keg Shifts in Range", f"{4 - after_m['keg_band_breaches']:,} / 4")

    compare = smoothing_compare_table(before_state, after_state, after_label)

    st.write(f"**Warehouse Volume - Current vs {after_label}**")
    volume_view = compare[[
        "Workload Shift",
        "Metro Delivery Day",
        "Regional Delivery Day",
        "Current Total Cartons",
        "Current Total Cartons %",
        f"{after_label} Total Cartons",
        f"{after_label} Total Cartons %",
        "Total Cartons Status",
        "Current Keg Picks",
        "Current Keg Picks %",
        f"{after_label} Keg Picks",
        f"{after_label} Keg Picks %",
        "Keg Picks Status"
    ]].copy()

    st.dataframe(
        volume_view.style.format({
            "Current Total Cartons": "{:,.0f}",
            "Current Total Cartons %": "{:.1%}",
            f"{after_label} Total Cartons": "{:,.0f}",
            f"{after_label} Total Cartons %": "{:.1%}",
            "Current Keg Picks": "{:,.0f}",
            "Current Keg Picks %": "{:.1%}",
            f"{after_label} Keg Picks": "{:,.0f}",
            f"{after_label} Keg Picks %": "{:.1%}"
        }),
        use_container_width=True,
        hide_index=True
    )

    st.write(f"**Pick Method Workload - Current vs {after_label}**")
    method_view = compare[[
        "Workload Shift",
        "Current Pallet Picks", "Current Pallet Picks %",
        f"{after_label} Pallet Picks", f"{after_label} Pallet Picks %", "Pallet Picks Status",
        "Current Layer Picks", "Current Layer Picks %",
        f"{after_label} Layer Picks", f"{after_label} Layer Picks %", "Layer Picks Status",
        "Current Carton Picks", "Current Carton Picks %",
        f"{after_label} Carton Picks", f"{after_label} Carton Picks %", "Carton Picks Status"
    ]].copy()

    fmt = {}
    for label in ["Pallet Picks", "Layer Picks", "Carton Picks"]:
        fmt[f"Current {label}"] = "{:,.0f}"
        fmt[f"Current {label} %"] = "{:.1%}"
        fmt[f"{after_label} {label}"] = "{:,.0f}"
        fmt[f"{after_label} {label} %"] = "{:.1%}"

    st.dataframe(
        method_view.style.format(fmt),
        use_container_width=True,
        hide_index=True
    )

    return before_m, after_m

# ==========================================================
