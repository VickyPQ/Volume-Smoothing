"""Business configuration and operating constraints."""

# ==========================================================

PLANT_TO_ANALYSE = 1034
IMPACT_ISLAND = "North Island"


ROUTE_DAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday"
]


WAREHOUSE_DAY_ORDER = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday"
]


ALL_DAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday"
]


DAY_IDX = {
    day: i
    for i, day in enumerate(ALL_DAY_ORDER)
}


SHORT_TO_FULL = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday"
}

DAY_VALUE_TO_FULL = {
    **{k.lower(): v for k, v in SHORT_TO_FULL.items()},
    **{v.lower(): v for v in SHORT_TO_FULL.values()}
}

NUMERIC_DAY_TO_FULL = {
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
    "7": "Sunday"
}

SEASON_ORDER = [
    "May-Sep",
    "Oct-Dec",
    "Jan-Apr"
]


# ==========================================================
# PICK SCHEDULE
# ==========================================================

# Metro
# Sunday -> Monday delivery
# Monday -> Tuesday delivery
# Tuesday -> Wednesday delivery
# Wednesday -> Thursday delivery
# Thursday -> Friday delivery

METRO_PICK_MAP = {
    "Monday": "Sunday",
    "Tuesday": "Monday",
    "Wednesday": "Tuesday",
    "Thursday": "Wednesday",
    "Friday": "Thursday"
}


# Regional
# Friday -> Monday delivery
# Monday -> Tuesday delivery
# Tuesday -> Wednesday delivery
# Wednesday -> Thursday delivery
# Thursday -> Friday delivery

REGIONAL_PICK_MAP = {
    "Monday": "Friday",
    "Tuesday": "Monday",
    "Wednesday": "Tuesday",
    "Thursday": "Wednesday",
    "Friday": "Thursday"
}


REMOVED_PICK_DAY_BY_GROUP = {
    "Metro": "Thursday",
    "Regional": "Friday"
}

# Current delivery days that must be removed in the future model.
IMPACTED_DELIVERY_DAY_BY_GROUP = {
    "Metro": "Friday",
    "Regional": "Monday"
}


# ==========================================================
# WAREHOUSE OPTIMISATION RULES
# ==========================================================

# Current 5 warehouse shifts are paired by the physical work window:
#   Shift 1 = Metro Sunday pick    + Regional Monday pick
#   Shift 2 = Metro Monday pick    + Regional Tuesday pick
#   Shift 3 = Metro Tuesday pick   + Regional Wednesday pick
#   Shift 4 = Metro Wednesday pick + Regional Thursday pick
#   Shift 5 = Metro Thursday pick  + Regional Friday pick
#
# Future 4WD removes Metro Thursday pick and Regional Friday pick, so
# optimisation smooths Shift 1-4 only.

GROUP_FUTURE_DELIVERY_DAYS = {
    "Metro": ["Monday", "Tuesday", "Wednesday", "Thursday"],
    "Regional": ["Tuesday", "Wednesday", "Thursday", "Friday"]
}

GROUP_FUTURE_PICK_DAYS = {
    "Metro": ["Sunday", "Monday", "Tuesday", "Wednesday"],
    "Regional": ["Monday", "Tuesday", "Wednesday", "Thursday"]
}

CUSTOMER_GROUPS = ["Metro", "Regional"]

CURRENT_SHIFT_MAP = {
    "Shift 1": {"Metro": "Sunday", "Regional": "Monday"},
    "Shift 2": {"Metro": "Monday", "Regional": "Tuesday"},
    "Shift 3": {"Metro": "Tuesday", "Regional": "Wednesday"},
    "Shift 4": {"Metro": "Wednesday", "Regional": "Thursday"},
    "Shift 5": {"Metro": "Thursday", "Regional": "Friday"}
}

FUTURE_SHIFT_MAP = {
    key: value
    for key, value in CURRENT_SHIFT_MAP.items()
    if key != "Shift 5"
}

CURRENT_SHIFT_ORDER = list(CURRENT_SHIFT_MAP.keys())
FUTURE_SHIFT_ORDER = list(FUTURE_SHIFT_MAP.keys())

FUTURE_SHIFT_DELIVERY_MAP = {
    "Shift 1": {"Metro": "Monday", "Regional": "Tuesday"},
    "Shift 2": {"Metro": "Tuesday", "Regional": "Wednesday"},
    "Shift 3": {"Metro": "Wednesday", "Regional": "Thursday"},
    "Shift 4": {"Metro": "Thursday", "Regional": "Friday"}
}

# Physical pick days retained for raw current-state warehouse views.
FUTURE_PICK_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"]

# Every future workload measure targets 25% per shift.
# 23%-27% is the acceptable operating band.
GROUP_TARGET_SHARE = 0.25
GROUP_MIN_SHARE = 0.23
GROUP_MAX_SHARE = 0.27

WAREHOUSE_MEASURES = [
    "Cartons",
    "Pallet Picks",
    "Layer Picks",
    "Carton Picks",
    "Keg Picks"
]

# Total Cartons is the first optimisation priority.
# Pallet, Layer, Carton and Keg workloads are equally weighted after it.
SECONDARY_SMOOTHING_MEASURES = [
    "Pallet Picks",
    "Layer Picks",
    "Carton Picks",
    "Keg Picks"
]

MEASURE_LABELS = {
    "Cartons": "Total Cartons",
    "Pallet Picks": "Pallet Picks",
    "Layer Picks": "Layer Picks",
    "Carton Picks": "Carton Picks",
    "Keg Picks": "Keg Picks"
}
