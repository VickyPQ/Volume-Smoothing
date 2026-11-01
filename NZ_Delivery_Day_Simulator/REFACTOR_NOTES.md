# Refactor notes

## What changed

- Split the original 5,807-line script into configuration, loading,
  transformation, aggregation, simulation, runtime and UI modules.
- Kept Streamlit caching at the runtime orchestration boundary.
- Removed Streamlit dependencies from the loader and calculation modules.
- Preserved the original tab labels and execution order.
- Added focused tests for weekday normalization, customer-group normalization,
  date parsing and removed delivery-day rules.
- Added project metadata, dependency definitions, Git exclusions and setup
  instructions.

## Behaviour-preservation approach

The existing source statements were moved with minimal edits. The only
calculation-interface change is that `build_aggregations` now receives
`route_set_days` explicitly instead of reading it as an implicit global.

## Required parity check

The source data files were not supplied with the Python script, so a complete
before/after output comparison could not be run. Before production use, compare
both versions using the same fixed files and selections. At minimum, validate:

- network customer and route counts;
- impacted customer and route counts;
- route/day gross weight and keg totals;
- warehouse cartons and pick-method totals;
- optimisation assignments and moved volumes;
- four-shift shares, peaks and reconciliation totals;
- negotiation and carrier-benefit outputs.

## Next safe extraction

The global optimiser is still orchestrated from its Streamlit tab because its
solver construction and result presentation are heavily interleaved in the
original code. After output parity is signed off, extract the PuLP model into a
pure `run_global_optimisation(...)` calculation function and leave only input
collection and result rendering in `ui/optimisation.py`.
