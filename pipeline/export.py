"""
export.py - Writes the star schema as CSV files that Power BI loads from a folder.

One file per table, all companies together (a 'company' column tells them apart),
so a new company shows up in the report without touching the Power BI model.
Files are UTF-8 with BOM, which Excel and Power BI open correctly.
"""

import csv
from datetime import date, timedelta
from pathlib import Path

from . import schema


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {path.name:<24} {len(rows):>6} rows")


def date_table(first: date, last: date) -> list[dict]:
    """A full calendar (Power BI time intelligence needs every day, no gaps)."""
    rows, day = [], date(first.year, 1, 1)
    while day <= date(last.year, 12, 31):
        rows.append({
            "date": day.isoformat(), "year": day.year, "month": day.month,
            "month_name": day.strftime("%b"), "year_month": day.strftime("%Y-%m"),
            "quarter": f"Q{(day.month - 1) // 3 + 1}", "half": f"H{1 if day.month <= 6 else 2}",
            "weekday": day.strftime("%a"), "iso_week": day.isocalendar()[1],
        })
        day += timedelta(days=1)
    return rows


def export_all(connectors, output: Path) -> dict[str, list[dict]]:
    """Reads every connector and writes all tables. Returns the tables (used by the checks)."""
    tables = {"fact_transactions": [], "dim_category": [], "dim_cost_center": [],
              "dim_account": [], "dim_company": []}
    for c in connectors:
        print(f"[{c.company_code}] {c.company_name}")
        tables["fact_transactions"] += c.transactions()
        tables["dim_category"] += c.categories()
        tables["dim_cost_center"] += c.cost_centers()
        tables["dim_account"] += c.accounts()
        tables["dim_company"].append({"code": c.company_code, "name": c.company_name})

    dates = [r[k] for r in tables["fact_transactions"]
             for k in ("due_date", "accrual_date", "payment_date") if r.get(k)]
    if dates:
        tables["dim_date"] = date_table(date.fromisoformat(min(dates)),
                                        date.fromisoformat(max(dates)))

    print(f"\nWriting to '{output}':")
    columns = {"fact_transactions": schema.FACT_TRANSACTIONS, "dim_category": schema.DIM_CATEGORY,
               "dim_cost_center": schema.DIM_COST_CENTER, "dim_account": schema.DIM_ACCOUNT,
               "dim_company": schema.DIM_COMPANY, "dim_date": schema.DIM_DATE}
    for name, rows in tables.items():
        write_csv(output / f"{name}.csv", rows, columns[name])
    return tables
