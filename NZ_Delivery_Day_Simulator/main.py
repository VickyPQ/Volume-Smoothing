"""Streamlit entry point."""

import streamlit as st

st.set_page_config(page_title="Delivery Day Change Simulator", layout="wide")

from simulator.ui.carrier_benefit import render_carrier_benefit
from simulator.ui.customers import render_customers
from simulator.ui.negotiation import render_negotiation
from simulator.ui.network import render_network
from simulator.ui.optimisation import render_optimisation
from simulator.ui.scenarios import render_scenarios


st.title("Delivery Day Change - Impact Simulator")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    [
        "1. Current Network Overview",
        "2. Impacted Customers - North Island",
        "3. Global Warehouse Optimisation",
        "4. Customer Recommendation / Scenario",
        "5. Negotiation Tracker",
        "6. Carrier Benefit",
    ]
)

# Preserve the original execution order because later tabs may use session
# state initialized by the scenario tab.
with tab1:
    render_network()
with tab2:
    render_customers()
with tab4:
    render_scenarios()
with tab3:
    render_optimisation()
with tab5:
    render_negotiation()
with tab6:
    render_carrier_benefit()
