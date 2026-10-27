# Power BI model

Load the CSV files from the pipeline's output folder (`data_powerbi/`) and relate them like this:

| From | To | Type |
| --- | --- | --- |
| `fact_transactions[accrual_date]` | `dim_date[date]` | Many to one, **active** (P&L by accrual month) |
| `fact_transactions[payment_date]` | `dim_date[date]` | Many to one, inactive (cash flow, used through `USERELATIONSHIP`) |
| `fact_transactions[due_date]` | `dim_date[date]` | Many to one, inactive (aging and forecasts) |
| `fact_transactions[category_key]` | `dim_category[category_key]` | Many to one (key = company + category id) |
| `fact_transactions[company]` | `dim_company[code]` | Many to one |

Files:

- `load_csv.pq` - Power Query template for each table, with a `DataFolder` parameter.
- `measures.dax` - Revenue, expenses, operating result and margin, YTD, month-over-month, cash in and out, open receivables and payables, and data-quality counts.

Report pages used in production: **P&L** (matrix by category and month, KPI cards, revenue vs. expenses), **Cash Flow** (cash in/out by payment date, balance by bank account), and **Data Checks** (`data_quality.csv`: entries to fix in the ERP).
