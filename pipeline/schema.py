"""
schema.py - The star schema that Power BI reads.

Every connector (sample data, Conta Azul, or any other ERP) returns rows in
these shapes, so the CSV export and the Power BI model never change when the
data source does.

    fact_transactions ──┬── dim_date          (due_date, accrual_date, payment_date)
                        ├── dim_company
                        ├── dim_category      (P&L line and group)
                        ├── dim_cost_center
                        └── dim_account       (bank / cash accounts)
"""

FACT_TRANSACTIONS = [
    "id", "company", "type", "description",
    "due_date", "accrual_date", "payment_date", "status",
    "amount", "amount_paid", "amount_open",
    "category_id", "cost_center_id", "account_id",
    "counterparty_id", "counterparty_name", "payment_method",
    "created_at", "updated_at",
]

DIM_CATEGORY = ["company", "id", "name", "type", "parent_id", "pnl_group", "in_pnl"]
DIM_COST_CENTER = ["company", "id", "name", "code", "active"]
DIM_ACCOUNT = ["company", "id", "name", "type", "bank", "active", "is_default", "balance"]
DIM_COMPANY = ["code", "name"]
DIM_DATE = ["date", "year", "month", "month_name", "year_month", "quarter", "half",
            "weekday", "iso_week"]

REVENUE, EXPENSE = "revenue", "expense"
PAID, PARTIAL, OPEN, OVERDUE = "paid", "partially_paid", "open", "overdue"
