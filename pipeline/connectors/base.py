"""
base.py - What every data source must provide.

A connector reads one company from one system and returns plain dicts in the
shapes defined in schema.py. Adding a new ERP means writing one new connector;
the export, the data checks and the Power BI model stay the same.
"""

from typing import Protocol


class Connector(Protocol):
    company_code: str
    company_name: str

    def transactions(self) -> list[dict]:
        """Receivables and payables (schema.FACT_TRANSACTIONS)."""

    def categories(self) -> list[dict]:
        """Chart of accounts used for the P&L (schema.DIM_CATEGORY)."""

    def cost_centers(self) -> list[dict]:
        """schema.DIM_COST_CENTER"""

    def accounts(self) -> list[dict]:
        """Bank and cash accounts with their balance (schema.DIM_ACCOUNT)."""
