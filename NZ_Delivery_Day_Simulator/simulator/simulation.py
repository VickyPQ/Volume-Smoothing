"""Pure scenario and warehouse calculations with no Streamlit dependency."""

import numpy as np
import pandas as pd

from simulator.config import *  # noqa: F403
from simulator.transformations import *  # noqa: F403

def safe_divide(numerator, denominator):

    if denominator is None or pd.isna(denominator) or float(denominator) == 0:
        return 0.0

    return float(numerator) / float(denominator)


def get_customer_configured_days(
    customer_id,
    route,
    delivery_day_df
):

    rows = delivery_day_df[
        (delivery_day_df["Customer ID"] == customer_id)
        & (delivery_day_df["Route"] == route)
    ].copy()

    days = (
        rows["Delivery Day Full"]
        .dropna()
        .loc[lambda x: x.isin(ROUTE_DAY_ORDER)]
        .drop_duplicates()
        .tolist()
    )

    return sort_days(list(dict.fromkeys(days)))


def get_customer_delivery_profile(
    customer_id,
    route,
    delivery_day_df,
    fact_df
):

    configured_days = get_customer_configured_days(
        customer_id,
        route,
        delivery_day_df
    )

    settings = delivery_day_df[
        (delivery_day_df["Customer ID"] == customer_id)
        & (delivery_day_df["Route"] == route)
    ][[
        "Delivery Day Full",
        "Impacted Delivery Day Row"
    ]].drop_duplicates().copy()

    settings["Delivery Day"] = settings["Delivery Day Full"]
    settings = settings[settings["Delivery Day"].isin(ROUTE_DAY_ORDER)].copy()

    history = (
        fact_df[
            (fact_df["Customer ID"] == customer_id)
            & (fact_df["Route"] == route)
            & (fact_df["Delivery Day"].isin(configured_days))
        ]
        .groupby("Delivery Day", observed=True)["Gross Weight"]
        .sum()
        .reset_index()
        .rename(columns={"Gross Weight": "Historical Gross Weight"})
    )

    profile = pd.DataFrame({"Delivery Day": configured_days})
    profile = profile.merge(history, on="Delivery Day", how="left")
    profile["Historical Gross Weight"] = profile["Historical Gross Weight"].fillna(0.0)

    impacted_days = set(
        settings.loc[
            settings["Impacted Delivery Day Row"].eq("Yes"),
            "Delivery Day"
        ].dropna().tolist()
    )

    total_weight = float(profile["Historical Gross Weight"].sum())
    profile["Share %"] = profile["Historical Gross Weight"].apply(
        lambda x: safe_divide(x, total_weight)
    )
    profile["Impacted Day"] = profile["Delivery Day"].apply(
        lambda x: "Yes" if x in impacted_days else "No"
    )
    profile["Delivery Day"] = pd.Categorical(
        profile["Delivery Day"],
        categories=ROUTE_DAY_ORDER,
        ordered=True
    )

    return profile.sort_values("Delivery Day"), configured_days, total_weight


def get_customer_move_payload(
    customer_id,
    route,
    old_day,
    customer_group,
    fact_df
):
    """Return workload for the exact current customer/route/delivery-day setting.

    For planning_fact, Pick Day is already the modelled planning pick day derived
    from Delivery Day + Customer Group. For the untouched historical fact table,
    Pick Day remains the actual historical pick day.
    """

    rows = fact_df[
        (fact_df["Customer ID"] == customer_id)
        & (fact_df["Route"] == route)
        & (fact_df["Delivery Day"] == old_day)
        & (fact_df["Customer Group"] == customer_group)
    ].copy()

    totals = {
        measure: float(rows[measure].sum())
        for measure in WAREHOUSE_MEASURES
    }
    totals["Gross Weight"] = float(rows["Gross Weight"].sum())
    totals["Keg Qty"] = float(rows["Keg Qty"].sum()) if "Keg Qty" in rows.columns else 0.0
    totals["Keg Gross Weight"] = float(rows["Keg Gross Weight"].sum()) if "Keg Gross Weight" in rows.columns else 0.0
    totals["Carton Gross Weight"] = float(rows["Carton Gross Weight"].sum()) if "Carton Gross Weight" in rows.columns else 0.0

    pick_distribution = (
        rows[rows["Pick Day"].isin(WAREHOUSE_DAY_ORDER)]
        .groupby("Pick Day", observed=True)[WAREHOUSE_MEASURES]
        .sum()
        .reset_index()
    )

    return totals, pick_distribution


def build_warehouse_state(warehouse_all_df):

    grid = pd.MultiIndex.from_product(
        [WAREHOUSE_DAY_ORDER, ["Metro", "Regional"]],
        names=["Pick Day", "Customer Group"]
    ).to_frame(index=False)

    state = grid.merge(
        warehouse_all_df,
        on=["Pick Day", "Customer Group"],
        how="left"
    )

    for measure in WAREHOUSE_MEASURES:
        if measure not in state.columns:
            state[measure] = 0.0
        state[measure] = pd.to_numeric(state[measure], errors="coerce").fillna(0.0)

    return state


def apply_move_to_warehouse_state(
    warehouse_state,
    customer_group,
    pick_distribution,
    totals,
    new_pick_day
):

    result = warehouse_state.copy()

    for _, pick_row in pick_distribution.iterrows():
        old_pick_day = pick_row["Pick Day"]
        mask = (
            result["Pick Day"].eq(old_pick_day)
            & result["Customer Group"].eq(customer_group)
        )

        for measure in WAREHOUSE_MEASURES:
            result.loc[mask, measure] -= float(pick_row.get(measure, 0.0))

    add_mask = (
        result["Pick Day"].eq(new_pick_day)
        & result["Customer Group"].eq(customer_group)
    )

    for measure in WAREHOUSE_MEASURES:
        result.loc[add_mask, measure] += float(totals.get(measure, 0.0))

    for measure in WAREHOUSE_MEASURES:
        result[measure] = result[measure].clip(lower=0)

    return result


def pick_day_serves_label(pick_day):
    """Short physical-pick description retained for internal use."""
    parts = []
    for group in CUSTOMER_GROUPS:
        pick_map = METRO_PICK_MAP if group == "Metro" else REGIONAL_PICK_MAP
        for delivery_day in GROUP_FUTURE_DELIVERY_DAYS[group]:
            if pick_map.get(delivery_day) == pick_day:
                parts.append(f"{group} {delivery_day[:3]}")
    return " + ".join(parts) if parts else ""


def shift_for_group_pick(customer_group, pick_day, future_only=True):
    mapping = FUTURE_SHIFT_MAP if future_only else CURRENT_SHIFT_MAP
    for shift, group_map in mapping.items():
        if group_map.get(customer_group) == pick_day:
            return shift
    return None


def shift_measure_value(warehouse_state, shift, measure, future_only=True):
    mapping = FUTURE_SHIFT_MAP if future_only else CURRENT_SHIFT_MAP
    if shift not in mapping:
        return 0.0

    total = 0.0
    for group, pick_day in mapping[shift].items():
        rows = warehouse_state[
            warehouse_state["Customer Group"].eq(group)
            & warehouse_state["Pick Day"].eq(pick_day)
        ]
        if measure in rows.columns:
            total += float(pd.to_numeric(rows[measure], errors="coerce").fillna(0.0).sum())
    return total


def current_five_shift_total(warehouse_state, measure):
    """Stable weekly denominator, including the current Shift 5 until it is removed."""
    return float(sum(
        shift_measure_value(warehouse_state, shift, measure, future_only=False)
        for shift in CURRENT_SHIFT_ORDER
    ))


def five_shift_detail(warehouse_state):
    """Current/final workload across all five shifts using the full weekly total as denominator.

    Shift 5 is visible for reconciliation. In the future optimised model it should be zero.
    """
    totals = {
        measure: current_five_shift_total(warehouse_state, measure)
        for measure in WAREHOUSE_MEASURES
    }

    rows = []
    for shift in CURRENT_SHIFT_ORDER:
        row = {
            "Workload Shift": shift,
            "Metro Pick Day": CURRENT_SHIFT_MAP[shift]["Metro"],
            "Regional Pick Day": CURRENT_SHIFT_MAP[shift]["Regional"],
        }
        if shift in FUTURE_SHIFT_DELIVERY_MAP:
            row["Metro Delivery Day"] = FUTURE_SHIFT_DELIVERY_MAP[shift]["Metro"]
            row["Regional Delivery Day"] = FUTURE_SHIFT_DELIVERY_MAP[shift]["Regional"]
        else:
            # Current removed shift: Metro Thu pick -> Fri delivery; Regional Fri pick -> Mon delivery.
            row["Metro Delivery Day"] = "Friday"
            row["Regional Delivery Day"] = "Monday"

        for measure in WAREHOUSE_MEASURES:
            value = shift_measure_value(warehouse_state, shift, measure, future_only=False)
            total = totals[measure]
            share = safe_divide(value, total)
            label = MEASURE_LABELS[measure]
            row[label] = value
            row[f"{label} Share"] = share

            if shift == "Shift 5":
                row[f"{label} Status"] = "Removed" if abs(value) <= 0.01 else "Still to move"
            else:
                ok = total == 0 or GROUP_MIN_SHARE <= share <= GROUP_MAX_SHARE
                row[f"{label} Status"] = "Within range" if ok else (
                    "Needs more volume" if share < GROUP_MIN_SHARE else "Too much volume"
                )

        rows.append(row)

    return pd.DataFrame(rows)


def shift_smoothing_detail(warehouse_state):
    """One row per future warehouse shift, with each workload method measured against 25%."""
    totals = {
        measure: current_five_shift_total(warehouse_state, measure)
        for measure in WAREHOUSE_MEASURES
    }

    rows = []
    for shift in FUTURE_SHIFT_ORDER:
        row = {
            "Workload Shift": shift,
            "Metro Pick Day": FUTURE_SHIFT_MAP[shift]["Metro"],
            "Regional Pick Day": FUTURE_SHIFT_MAP[shift]["Regional"],
            "Metro Delivery Day": FUTURE_SHIFT_DELIVERY_MAP[shift]["Metro"],
            "Regional Delivery Day": FUTURE_SHIFT_DELIVERY_MAP[shift]["Regional"]
        }

        for measure in WAREHOUSE_MEASURES:
            value = shift_measure_value(warehouse_state, shift, measure, future_only=True)
            total = totals[measure]
            share = safe_divide(value, total)
            ok = total == 0 or GROUP_MIN_SHARE <= share <= GROUP_MAX_SHARE

            label = MEASURE_LABELS[measure]
            row[label] = value
            row[f"{label} Share"] = share
            row[f"{label} Deviation (pp)"] = (
                abs(share - GROUP_TARGET_SHARE) * 100 if total > 0 else 0.0
            )
            row[f"{label} Status"] = "Within range" if ok else (
                "Needs more volume" if share < GROUP_MIN_SHARE else "Too much volume"
            )

        rows.append(row)

    return pd.DataFrame(rows)


def group_smoothing_detail(warehouse_state):
    """Backward-compatible alias: the app now smooths combined warehouse shifts."""
    return shift_smoothing_detail(warehouse_state)


def removed_day_volume(warehouse_state):
    """Current Shift 5 workload still awaiting re-assignment."""
    rows = []
    for group in CUSTOMER_GROUPS:
        removed_pick = REMOVED_PICK_DAY_BY_GROUP[group]
        matched = warehouse_state[
            warehouse_state["Customer Group"].eq(group)
            & warehouse_state["Pick Day"].eq(removed_pick)
        ]
        rows.append({
            "Customer Group": group,
            "Removed Pick Day": removed_pick,
            "Cartons": float(matched["Cartons"].sum()),
            "Keg Picks": float(matched["Keg Picks"].sum())
        })
    return pd.DataFrame(rows)


def pick_mix_detail(warehouse_state):
    """Future shift workload shares for Pallet, Layer and Carton pick methods."""
    return shift_smoothing_detail(warehouse_state)

def daily_balance_metrics(day_values):

    values = pd.Series(day_values, dtype="float64").fillna(0.0)
    total = float(values.sum())

    if total <= 0 or len(values) == 0:
        return {
            "peak_share": 0.0,
            "spread_share": 0.0,
            "deviation_pp": 0.0
        }

    shares = values / total
    target = 1.0 / len(shares)

    return {
        "peak_share": float(shares.max()),
        "spread_share": float(shares.max() - shares.min()),
        "deviation_pp": float((shares - target).abs().sum() * 100)
    }


def simulate_transport_move(
    route_day_volume_df,
    carrier_day_volume_df,
    route,
    carrier,
    old_day,
    new_day,
    moved_weight
):

    route_days_for_route = route_days.get(route, [])
    route_base = (
        route_day_volume_df[
            (route_day_volume_df["Route"] == route)
            & (route_day_volume_df["Is_Set_Day"].eq(True))
        ]
        .set_index("Delivery Day")["Gross Weight"]
        .reindex(route_days_for_route, fill_value=0.0)
        .astype(float)
    )

    route_after = route_base.copy()
    if old_day in route_after.index:
        route_after.loc[old_day] = max(0.0, route_after.loc[old_day] - moved_weight)
    if new_day in route_after.index:
        route_after.loc[new_day] += moved_weight

    carrier_base = (
        carrier_day_volume_df[
            carrier_day_volume_df["Carrier Name"] == carrier
        ]
        .groupby("Delivery Day", observed=True)["Gross Weight"]
        .sum()
        .reindex(ROUTE_DAY_ORDER, fill_value=0.0)
        .astype(float)
    )

    carrier_after = carrier_base.copy()
    if old_day in carrier_after.index:
        carrier_after.loc[old_day] = max(0.0, carrier_after.loc[old_day] - moved_weight)
    if new_day in carrier_after.index:
        carrier_after.loc[new_day] += moved_weight

    return (
        daily_balance_metrics(route_base.values),
        daily_balance_metrics(route_after.values),
        daily_balance_metrics(carrier_base.values),
        daily_balance_metrics(carrier_after.values),
        route_base,
        route_after,
        carrier_base,
        carrier_after
    )


def warehouse_metrics(warehouse_state):
    """Warehouse smoothing metrics across the four future combined shifts."""
    detail = shift_smoothing_detail(warehouse_state)

    def measure_metrics(label):
        dev_col = f"{label} Deviation (pp)"
        status_col = f"{label} Status"
        if detail.empty:
            return 0.0, 0.0, 0
        total_dev = float(detail[dev_col].sum())
        max_dev = float(detail[dev_col].max())
        breaches = int(detail[status_col].ne("Within range").sum())
        return total_dev, max_dev, breaches

    carton_total, carton_max, carton_breaches = measure_metrics("Total Cartons")
    pallet_total, pallet_max, pallet_breaches = measure_metrics("Pallet Picks")
    layer_total, layer_max, layer_breaches = measure_metrics("Layer Picks")
    carton_pick_total, carton_pick_max, carton_pick_breaches = measure_metrics("Carton Picks")
    keg_total, keg_max, keg_breaches = measure_metrics("Keg Picks")

    return {
        "carton_total_deviation_pp": carton_total,
        "carton_max_deviation_pp": carton_max,
        "carton_band_breaches": carton_breaches,
        "pallet_total_deviation_pp": pallet_total,
        "pallet_max_deviation_pp": pallet_max,
        "pallet_band_breaches": pallet_breaches,
        "layer_total_deviation_pp": layer_total,
        "layer_max_deviation_pp": layer_max,
        "layer_band_breaches": layer_breaches,
        "carton_pick_total_deviation_pp": carton_pick_total,
        "carton_pick_max_deviation_pp": carton_pick_max,
        "carton_pick_band_breaches": carton_pick_breaches,
        "keg_total_deviation_pp": keg_total,
        "keg_max_deviation_pp": keg_max,
        "keg_band_breaches": keg_breaches,
        # Backward-compatible names used by a few UI paths.
        "pallet_breaches": pallet_breaches,
        "mix_breaches": layer_breaches + carton_pick_breaches,
        "pallet_gap_cartons": 0.0,
        "mix_gap_cartons": 0.0,
        "total_cartons": current_five_shift_total(warehouse_state, "Cartons")
    }


def final_group_volume(warehouse_state, customer_group=None, measure="Cartons"):
    """Backward-compatible helper; smoothing is now one combined warehouse."""
    return current_five_shift_total(warehouse_state, measure)


def destination_capacity(warehouse_state, customer_group, pick_day):
    """Check whether the destination combined shift can take the proposed move."""
    shift = shift_for_group_pick(customer_group, pick_day, future_only=True)
    total_cartons = current_five_shift_total(warehouse_state, "Cartons")

    if shift is None or total_cartons <= 0:
        return {
            "Network Fit": "No future shift",
            "Destination Carton Share": 0.0,
            "Carton Room to 27%": 0.0,
            "Destination Cartons": 0.0,
            "Final Group Cartons": total_cartons,
            "Workload Shift": shift or ""
        }

    cartons = shift_measure_value(warehouse_state, shift, "Cartons", future_only=True)
    share = safe_divide(cartons, total_cartons)
    room_to_upper = max(0.0, GROUP_MAX_SHARE * total_cartons - cartons)

    if share > GROUP_MAX_SHARE + 1e-9:
        status = "Over range"
    elif share < GROUP_MIN_SHARE - 1e-9:
        status = "Can take more"
    else:
        status = "Within range"

    return {
        "Network Fit": status,
        "Destination Carton Share": share,
        "Carton Room to 27%": room_to_upper,
        "Destination Cartons": cartons,
        "Final Group Cartons": total_cartons,
        "Workload Shift": shift
    }


def balance_progress(base_value, confirmed_value, optimum_value):
    """% of the theoretically achievable smoothing improvement secured so far."""
    achievable = float(base_value) - float(optimum_value)
    secured = float(base_value) - float(confirmed_value)

    if achievable <= 1e-9:
        return 1.0 if confirmed_value <= base_value + 1e-9 else 0.0

    return max(0.0, min(1.0, secured / achievable))


def negotiation_capacity_table(warehouse_state):
    """Sales-facing capacity by combined future warehouse shift."""
    total_cartons = current_five_shift_total(warehouse_state, "Cartons")
    rows = []

    for shift in FUTURE_SHIFT_ORDER:
        cartons = shift_measure_value(warehouse_state, shift, "Cartons", future_only=True)
        share = safe_divide(cartons, total_cartons)
        room = max(0.0, GROUP_MAX_SHARE * total_cartons - cartons)

        if total_cartons <= 0:
            position = "No historical volume"
        elif share > GROUP_MAX_SHARE + 1e-9:
            position = "Too much volume"
        elif share < GROUP_MIN_SHARE - 1e-9:
            position = "Can take more"
        else:
            position = "Within range"

        rows.append({
            "Warehouse Shift": shift,
            "Metro Delivery Day": FUTURE_SHIFT_DELIVERY_MAP[shift]["Metro"],
            "Regional Delivery Day": FUTURE_SHIFT_DELIVERY_MAP[shift]["Regional"],
            "Confirmed Cartons": cartons,
            "Confirmed Carton %": share,
            "Network Position": position,
            "Room Before 27%": room
        })

    return pd.DataFrame(rows)


def warehouse_contribution_label(carton_improvement_pp, secondary_improvement_pp):
    combined = float(carton_improvement_pp) + 0.5 * float(secondary_improvement_pp)
    if combined >= 0.20:
        return "Strong improvement"
    if combined >= 0.02:
        return "Improves"
    if combined > -0.02:
        return "Near neutral"
    if combined > -0.20:
        return "Slightly worsens"
    return "Worsens"

def transport_balance_label(change_pp):
    """Business-friendly label. Negative change means the transport profile became more balanced."""
    change_pp = float(change_pp)
    if change_pp <= -0.20:
        return "Improves"
    if change_pp < -0.02:
        return "Slightly improves"
    if change_pp <= 0.02:
        return "Neutral"
    if change_pp < 0.20:
        return "Slightly worsens"
    return "Worsens"


def warehouse_need_for_candidate(warehouse_state, new_pick_day, customer_group):
    capacity = destination_capacity(warehouse_state, customer_group, new_pick_day)
    return capacity["Network Fit"]


def build_candidate_business_reason(warehouse_need, pick_mix_label, route_label, carrier_label):
    return warehouse_need


def evaluate_customer_candidate(
    warehouse_state,
    customer_id,
    route,
    carrier,
    old_day,
    new_day,
    customer_group,
    fact_df,
    route_day_volume_df,
    carrier_day_volume_df
):
    """Evaluate one customer move against the combined warehouse-shift target."""

    totals, pick_distribution = get_customer_move_payload(
        customer_id,
        route,
        old_day,
        customer_group,
        fact_df
    )

    new_pick_day = pick_day_from_delivery(new_day, customer_group)
    before_wh = warehouse_metrics(warehouse_state)

    scenario_wh = apply_move_to_warehouse_state(
        warehouse_state,
        customer_group,
        pick_distribution,
        totals,
        new_pick_day
    )
    after_wh = warehouse_metrics(scenario_wh)

    carton_improvement = (
        before_wh["carton_total_deviation_pp"]
        - after_wh["carton_total_deviation_pp"]
    )

    secondary_improvements = {
        "Pallet": before_wh["pallet_total_deviation_pp"] - after_wh["pallet_total_deviation_pp"],
        "Layer": before_wh["layer_total_deviation_pp"] - after_wh["layer_total_deviation_pp"],
        "Carton Pick": before_wh["carton_pick_total_deviation_pp"] - after_wh["carton_pick_total_deviation_pp"],
        "Keg": before_wh["keg_total_deviation_pp"] - after_wh["keg_total_deviation_pp"]
    }
    secondary_improvement = sum(secondary_improvements.values())

    capacity = destination_capacity(scenario_wh, customer_group, new_pick_day)

    (
        route_before,
        route_after,
        carrier_before,
        carrier_after,
        _, _, _, _
    ) = simulate_transport_move(
        route_day_volume_df,
        carrier_day_volume_df,
        route,
        carrier,
        old_day,
        new_day,
        totals["Gross Weight"]
    )

    route_balance_change = route_after["deviation_pp"] - route_before["deviation_pp"]
    carrier_balance_change = carrier_after["deviation_pp"] - carrier_before["deviation_pp"]

    route_impact = transport_balance_label(route_balance_change)
    carrier_impact = transport_balance_label(carrier_balance_change)

    # Total Cartons dominates. Pallet, Layer, Carton Pick and Keg are equal after it.
    ranking_score = (
        1000.0 * carton_improvement
        + 250.0 * secondary_improvement
        - 2.0 * route_balance_change
        - 1.0 * carrier_balance_change
    )

    return {
        "Proposed Delivery Day": new_day,
        "New Pick Day": new_pick_day,
        "Warehouse Contribution": warehouse_contribution_label(
            carton_improvement,
            secondary_improvement
        ),
        "Network Fit": capacity["Network Fit"],
        "Workload Shift": capacity["Workload Shift"],
        "Destination Carton Share": capacity["Destination Carton Share"],
        "Carton Room to 27%": capacity["Carton Room to 27%"],
        "Route Impact": route_impact,
        "Carrier Impact": carrier_impact,
        "Carton Balance Improvement (pp)": carton_improvement,
        "Pallet Balance Improvement (pp)": secondary_improvements["Pallet"],
        "Layer Balance Improvement (pp)": secondary_improvements["Layer"],
        "Carton Pick Balance Improvement (pp)": secondary_improvements["Carton Pick"],
        "Keg Balance Improvement (pp)": secondary_improvements["Keg"],
        "Moved Gross Weight": totals["Gross Weight"],
        "Moved Cartons": totals["Cartons"],
        "Moved Keg Picks": totals["Keg Picks"],
        "Ranking Score": ranking_score
    }
