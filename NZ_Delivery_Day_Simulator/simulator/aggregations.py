"""Network, warehouse and carrier aggregations with no UI dependency."""

import numpy as np
import pandas as pd

from simulator.config import *  # noqa: F403
from simulator.transformations import sort_days

def build_aggregations(
    fact_df,
    fact_set_df,
    network_routes_df,
    route_set_days_df
):

    route_volume_actual = (
        fact_set_df
        .groupby(
            ["Island", "Carrier Name", "Route", "Delivery Day"],
            observed=True
        )
        .agg({
            "Gross Weight": "sum",
            "Keg Qty": "sum",
            "Keg Gross Weight": "sum",
            "Carton Gross Weight": "sum"
        })
        .reset_index()
    )

    day_grid = pd.DataFrame({"Delivery Day": ROUTE_DAY_ORDER})
    route_grid = network_routes_df.merge(day_grid, how="cross")

    route_day_volume = route_grid.merge(
        route_volume_actual,
        on=["Island", "Carrier Name", "Route", "Delivery Day"],
        how="left"
    )
    route_day_volume["Gross Weight"] = pd.to_numeric(
        route_day_volume["Gross Weight"], errors="coerce"
    ).fillna(0.0)
    route_day_volume["Keg Qty"] = pd.to_numeric(
        route_day_volume["Keg Qty"], errors="coerce"
    ).fillna(0.0)
    route_day_volume["Keg Gross Weight"] = pd.to_numeric(
        route_day_volume["Keg Gross Weight"], errors="coerce"
    ).fillna(0.0)
    route_day_volume["Carton Gross Weight"] = pd.to_numeric(
        route_day_volume["Carton Gross Weight"], errors="coerce"
    ).fillna(0.0)

    route_day_volume = route_day_volume.merge(
        route_set_days_df.assign(Is_Set_Day=True),
        on=["Route", "Delivery Day"],
        how="left"
    )
    route_day_volume["Is_Set_Day"] = route_day_volume["Is_Set_Day"].eq(True)
    route_day_volume.loc[
        ~route_day_volume["Is_Set_Day"],
        ["Gross Weight", "Keg Qty", "Keg Gross Weight", "Carton Gross Weight"]
    ] = 0.0

    route_total = (
        route_day_volume
        .groupby(["Island", "Carrier Name", "Route"], observed=True)
        .agg(
            **{
                "Route Total Weight": ("Gross Weight", "sum"),
                "Route Total Keg Qty": ("Keg Qty", "sum")
            }
        )
        .reset_index()
    )

    route_day_volume = route_day_volume.merge(
        route_total,
        on=["Island", "Carrier Name", "Route"],
        how="left"
    )
    route_day_volume["Route Day Share"] = (
        route_day_volume["Gross Weight"]
        / route_day_volume["Route Total Weight"].replace(0, pd.NA)
    )
    route_day_volume["Route Keg Day Share"] = (
        route_day_volume["Keg Qty"]
        / route_day_volume["Route Total Keg Qty"].replace(0, pd.NA)
    )

    carrier_day_volume = (
        route_day_volume
        .groupby(["Island", "Carrier Name", "Delivery Day"], observed=True)
        .agg({
            "Gross Weight": "sum",
            "Keg Qty": "sum",
            "Keg Gross Weight": "sum",
            "Carton Gross Weight": "sum"
        })
        .reset_index()
    )

    carrier_total = (
        carrier_day_volume
        .groupby(["Island", "Carrier Name"], observed=True)
        .agg(
            **{
                "Carrier Total Weight": ("Gross Weight", "sum"),
                "Carrier Total Keg Qty": ("Keg Qty", "sum")
            }
        )
        .reset_index()
    )

    carrier_day_volume = carrier_day_volume.merge(
        carrier_total,
        on=["Island", "Carrier Name"],
        how="left"
    )
    carrier_day_volume["Carrier Day Share"] = (
        carrier_day_volume["Gross Weight"]
        / carrier_day_volume["Carrier Total Weight"].replace(0, pd.NA)
    )
    carrier_day_volume["Carrier Keg Day Share"] = (
        carrier_day_volume["Keg Qty"]
        / carrier_day_volume["Carrier Total Keg Qty"].replace(0, pd.NA)
    )

    customer_delivery_pick = (
        fact_df[fact_df["Pick Day"].isin(WAREHOUSE_DAY_ORDER)]
        .groupby(
            ["Customer ID", "Route", "Delivery Day", "Pick Day", "Customer Group"],
            observed=True
        )[WAREHOUSE_MEASURES]
        .sum()
        .reset_index()
    )

    warehouse_season = (
        fact_df[fact_df["Pick Day"].isin(WAREHOUSE_DAY_ORDER)]
        .groupby(["Season", "Pick Day", "Customer Group"], observed=True)[WAREHOUSE_MEASURES]
        .sum()
        .reset_index()
    )

    warehouse_all = (
        fact_df[fact_df["Pick Day"].isin(WAREHOUSE_DAY_ORDER)]
        .groupby(["Pick Day", "Customer Group"], observed=True)[WAREHOUSE_MEASURES]
        .sum()
        .reset_index()
    )

    return (
        route_day_volume,
        carrier_day_volume,
        customer_delivery_pick,
        warehouse_season,
        warehouse_all
    )


def carrier_benefit_base(planning_fact_df, delivery_day_df):
    """Per-drop history and per-customer move units (cached)."""
    pf = planning_fact_df[planning_fact_df["Island"].eq(IMPACT_ISLAND)].copy()
    weeks = max(1.0, (pf["Delivery Date"].max() - pf["Delivery Date"].min()).days / 7.0)

    drops = (
        pf.groupby(
            ["Carrier Name", "Route", "Delivery Day", "Customer ID", "Customer Group", "Delivery Date"],
            observed=True
        )[["Gross Weight", "Keg Qty"]].sum().reset_index()
    )

    cfg = delivery_day_df[delivery_day_df["Delivery Day Full"].isin(ROUTE_DAY_ORDER)]
    customer_days = (
        cfg.groupby(["Customer ID", "Route"])["Delivery Day Full"]
        .apply(lambda x: sort_days(x.unique().tolist()))
        .to_dict()
    )
    return drops, customer_days, weeks


def carrier_benefit_route_days(drops, customer_days, weeks, assignment_df, carrier=None):
    """Route x weekday table: per-week runs / drops / kg / kegs, Before vs After.

    After = the optimiser's recommended day for every impacted customer:
      * removed day (Metro Fri / Regional Mon) no longer runs;
      * recommended day is one the customer already has -> volume MERGES into that
        visit (the stop disappears);
      * recommended day is new for the customer -> the stop MOVES to that day;
      * customer not in the optimiser plan -> stays (exception).
    """
    d = drops if carrier is None else drops[drops["Carrier Name"].eq(carrier)]
    if d.empty:
        return pd.DataFrame(), pd.DataFrame()

    def per_week(frame):
        out = (
            frame.groupby(["Carrier Name", "Route", "Delivery Day"], observed=True)
            .agg(Runs=("Delivery Date", "nunique"), Drops=("Customer ID", "size"),
                 **{"Gross Weight": ("Gross Weight", "sum"), "Keg Qty": ("Keg Qty", "sum")})
            .reset_index()
        )
        out[CB_COLUMNS] = out[CB_COLUMNS] / weeks
        return out

    plan = {
        (int(c), str(r)): dday for c, r, dday in zip(
            assignment_df["Customer ID"], assignment_df["Route"], assignment_df["Recommended Delivery Day"])
    }

    removed_mask = np.array([
        IMPACTED_DELIVERY_DAY_BY_GROUP.get(g) == day
        for g, day in zip(d["Customer Group"], d["Delivery Day"])
    ])
    before = per_week(d)
    after = per_week(d[~removed_mask])

    adds, moves = [], []
    for (cid, route, old_day, carrier_name), grp in d[removed_mask].groupby(
        ["Customer ID", "Route", "Delivery Day", "Carrier Name"], observed=True
    ):
        drops_w = len(grp) / weeks
        kg_w = grp["Gross Weight"].sum() / weeks
        kegs_w = grp["Keg Qty"].sum() / weeks
        existing = [x for x in customer_days.get((cid, route), []) if x != old_day]
        dest = plan.get((int(cid), str(route)))
        if dest is None:
            dest, how, new_drops = old_day, "Not in optimiser plan - stays", drops_w
        elif dest in existing:
            how, new_drops = "Merged into existing visit", 0.0
        else:
            how, new_drops = "Moved to new day", drops_w
        adds.append((carrier_name, route, dest, new_drops, kg_w, kegs_w, new_drops))
        moves.append({"Customer ID": cid, "Route": route, "Removed Day": old_day, "New Day": dest,
                      "Outcome": how, "Drops / wk": drops_w, "Gross Weight / wk": kg_w, "Keg Qty / wk": kegs_w})

    if adds:
        add_df = (pd.DataFrame(adds, columns=["Carrier Name", "Route", "Delivery Day", "Drops",
                                              "Gross Weight", "Keg Qty", "_new_drops"])
                  .groupby(["Carrier Name", "Route", "Delivery Day"], observed=True).sum().reset_index())
        after = after.merge(add_df, on=["Carrier Name", "Route", "Delivery Day"], how="outer",
                            suffixes=("", "_add")).fillna(0.0)
        for c in ["Drops", "Gross Weight", "Keg Qty"]:
            after[c] = after[c] + after[f"{c}_add"]
        # A day the route did not run before needs a run for the moved drops (max 1 per week).
        after["Runs"] = np.where(after["Runs"] > 0, after["Runs"], np.minimum(1.0, after["_new_drops"]))
        after = after[["Carrier Name", "Route", "Delivery Day"] + CB_COLUMNS]

    table = before.merge(after, on=["Carrier Name", "Route", "Delivery Day"], how="outer",
                         suffixes=(" Before", " After")).fillna(0.0)
    return table, pd.DataFrame(moves)
