# NZ Delivery Day Change Simulator

This is the modular refactor of the original single-file Streamlit application.
The refactor preserves the existing business rules while separating data loading,
transformations, aggregations, simulation logic and presentation.

## Project structure

- `main.py` - Streamlit entry point and tab orchestration
- `simulator/config.py` - business constants and constraints
- `simulator/data_loader.py` - source reads and schema validation
- `simulator/transformations.py` - cleaning and normalization
- `simulator/aggregations.py` - network, warehouse and carrier aggregations
- `simulator/simulation.py` - scenario and warehouse calculations
- `simulator/runtime.py` - cached data orchestration
- `simulator/ui/` - presentation code for each tab
- `tests/` - focused business-rule and transformation tests

## Source files

Place these files in the project root. They are intentionally excluded from Git:

- `Billing_Raw.csv`
- `Delivery Day.xlsx`
- `Route Data.xlsx`

## Run locally

```bash
uv sync
uv run pytest
uv run streamlit run main.py
```

## Parity validation

Before deploying, run the original and refactored versions against the same fixed
input files and compare customer counts, route weights, warehouse cartons, moved
volumes, peak shifts and recommended delivery days. Structural and unit checks do
not replace this business-output comparison.
