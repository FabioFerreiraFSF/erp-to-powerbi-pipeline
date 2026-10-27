"""
checks.py - Data-quality checks before anyone trusts the dashboard.

A P&L is only as good as its bookkeeping. These checks list the entries that
would distort the report, so the finance team fixes them in the ERP:

  - no category            -> the amount is missing from the P&L
  - expense with no cost center -> cost by department is understated
  - paid with no bank account   -> cash flow by account does not reconcile
  - no counterparty        -> no vendor or customer analysis
  - overdue                -> collections and payments to chase

Output: data_quality.csv (one row per issue) and a completeness summary per field.
"""

from .schema import EXPENSE, OVERDUE, PAID, PARTIAL

CHECKS = [
    ("missing_category", "No category: amount is left out of the P&L",
     lambda r: not r["category_id"]),
    ("missing_cost_center", "Expense with no cost center",
     lambda r: r["type"] == EXPENSE and not r["cost_center_id"]),
    ("missing_bank_account", "Paid with no bank account",
     lambda r: r["status"] in (PAID, PARTIAL) and not r["account_id"]),
    ("missing_counterparty", "No vendor or customer",
     lambda r: not r["counterparty_name"]),
    ("overdue", "Overdue and still open",
     lambda r: r["status"] == OVERDUE),
]

DATA_QUALITY = ["company", "transaction_id", "check", "detail", "due_date", "description", "amount"]


def run_checks(transactions: list[dict]) -> list[dict]:
    issues = []
    for r in transactions:
        for code, detail, failed in CHECKS:
            if failed(r):
                issues.append({"company": r["company"], "transaction_id": r["id"], "check": code,
                               "detail": detail, "due_date": r["due_date"],
                               "description": r["description"], "amount": r["amount"]})
    return issues


def completeness(transactions: list[dict]) -> dict[str, float]:
    """Share of entries (%) with each key field filled in."""
    total = len(transactions) or 1
    expenses = [r for r in transactions if r["type"] == EXPENSE] or [{}]
    paid = [r for r in transactions if r["status"] in (PAID, PARTIAL)] or [{}]
    return {
        "category": 100 * sum(bool(r["category_id"]) for r in transactions) / total,
        "cost center (expenses)": 100 * sum(bool(r.get("cost_center_id")) for r in expenses) / len(expenses),
        "bank account (paid)": 100 * sum(bool(r.get("account_id")) for r in paid) / len(paid),
        "counterparty": 100 * sum(bool(r["counterparty_name"]) for r in transactions) / total,
    }
