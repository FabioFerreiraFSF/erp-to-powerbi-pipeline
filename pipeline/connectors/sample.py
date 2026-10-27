"""
sample.py - A fake ERP with realistic, 100% synthetic data.

Two companies of a fictional group (Northwind Advisory Group), monthly client
fees, payroll, rent, software, taxes and one-off expenses, from January 2024 to
the end of 2026. A fixed random seed makes every run identical, so the demo,
the tests and the dashboard screenshots always match.

A few data-quality problems are planted on purpose (missing category, missing
cost center, missing bank account) so the data checks have something to find.
"""

import random
from datetime import date, timedelta

from ..schema import EXPENSE, OPEN, OVERDUE, PAID, PARTIAL, REVENUE

START = date(2024, 1, 1)
END = date(2026, 12, 31)
TODAY = date(2026, 10, 15)          # fixed "today": decides what is paid, open or overdue

COMPANIES = {
    "NWA": ("Northwind Advisory LLC", 1.0),
    "NWC": ("Northwind Capital LLC", 0.45),       # smaller company: 45% of the volume
}

CATEGORIES = [
    # id, name, type, parent, P&L group
    ("rev-100", "Advisory Fees", REVENUE, "", "Revenue"),
    ("rev-110", "Consulting Projects", REVENUE, "", "Revenue"),
    ("rev-190", "Other Income", REVENUE, "", "Other Income"),
    ("exp-200", "Payroll", EXPENSE, "", "Cost of Services"),
    ("exp-210", "Payroll Taxes & Benefits", EXPENSE, "exp-200", "Cost of Services"),
    ("exp-300", "Rent", EXPENSE, "", "Operating Expenses"),
    ("exp-310", "Software & Subscriptions", EXPENSE, "", "Operating Expenses"),
    ("exp-320", "Professional Fees", EXPENSE, "", "Operating Expenses"),
    ("exp-330", "Marketing", EXPENSE, "", "Operating Expenses"),
    ("exp-340", "Travel & Meals", EXPENSE, "", "Operating Expenses"),
    ("exp-350", "Insurance", EXPENSE, "", "Operating Expenses"),
    ("exp-360", "Bank Fees", EXPENSE, "", "Operating Expenses"),
    ("exp-400", "Income Taxes", EXPENSE, "", "Taxes"),
    ("tr-900", "Owner Contributions", REVENUE, "", ""),   # not in the P&L
]

COST_CENTERS = [("cc-01", "Advisory", "ADV"), ("cc-02", "Consulting", "CON"),
                ("cc-03", "Administration", "ADM"), ("cc-04", "Sales", "SAL")]

ACCOUNTS = [("acc-01", "Operating Account", "checking", "First Harbor Bank", True),
            ("acc-02", "Payroll Account", "checking", "First Harbor Bank", False),
            ("acc-03", "Reserve Savings", "savings", "Summit Credit Union", False)]

CLIENTS = ["Harbor Logistics Inc", "Bluepeak Dental Group", "Cedar & Pine Architects",
           "Redwood Family Office", "Lakeside Manufacturing", "Orion Health Partners"]

FIXED_EXPENSES = [
    # description, category, cost center, vendor, min, max, due day
    ("Payroll", "exp-200", "cc-01", "Gusto Payroll", 28_000, 33_000, 28),
    ("Payroll taxes and benefits", "exp-210", "cc-01", "Gusto Payroll", 5_000, 6_500, 28),
    ("Office rent", "exp-300", "cc-03", "Elm Street Properties", 5_200, 5_200, 1),
    ("Software subscriptions", "exp-310", "cc-03", "CloudDesk Software", 1_100, 1_900, 10),
    ("Accounting and legal", "exp-320", "cc-03", "Summit Legal Partners", 2_000, 4_500, 15),
    ("Business insurance", "exp-350", "cc-03", "Shield Mutual Insurance", 900, 900, 20),
    ("Bank fees", "exp-360", "cc-03", "First Harbor Bank", 40, 160, 5),
]

ONE_OFF = [("exp-330", "Sales", "Brightline Marketing", 800, 9_000),
           ("exp-340", "Sales", "Skyway Travel", 300, 4_200),
           ("exp-320", "Administration", "Summit Legal Partners", 1_500, 12_000),
           ("exp-310", "Administration", "Acme Office Supplies", 150, 2_400)]


def _months():
    d = START
    while d <= END:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def _status(rng, due, partial_ok):
    """Paid, partially paid, open or overdue, as of the fixed TODAY."""
    if due > TODAY:
        return OPEN, 0.0, ""
    roll = rng.random()
    recent = (TODAY - due).days < 120                # old items are always settled by now
    if recent and roll < 0.12:
        return OVERDUE, 0.0, ""
    if recent and partial_ok and roll < 0.18:
        return PARTIAL, rng.uniform(0.3, 0.7), ""
    paid_on = min(due + timedelta(days=rng.randint(-3, 12)), TODAY)
    return PAID, 1.0, paid_on.isoformat()


class SampleConnector:
    def __init__(self, company_code: str = "NWA", seed: int = 42):
        self.company_code = company_code
        self.company_name, self.scale = COMPANIES[company_code]
        self.rng = random.Random(f"{seed}-{company_code}")
        self._next_id = 1

    def _row(self, kind, desc, due, amount, category, cost_center, account, party, method,
             partial_ok=False):
        status, paid_share, paid_on = _status(self.rng, due, partial_ok)
        amount = round(amount, 2)
        paid = round(amount * paid_share, 2)
        row = {
            "id": f"{self.company_code}-{self._next_id:05d}", "company": self.company_code,
            "type": kind, "description": desc,
            "due_date": due.isoformat(), "accrual_date": due.replace(day=1).isoformat(),
            "payment_date": paid_on, "status": status,
            "amount": amount, "amount_paid": paid, "amount_open": round(amount - paid, 2),
            "category_id": category, "cost_center_id": cost_center, "account_id": account,
            "counterparty_id": "cp-" + party.lower().replace(" ", "-").replace("&", "and"),
            "counterparty_name": party, "payment_method": method,
            "created_at": (due - timedelta(days=20)).isoformat() + "T09:00:00",
            "updated_at": (paid_on or (due - timedelta(days=20)).isoformat()) + "T09:00:00",
        }
        self._next_id += 1
        return row

    def transactions(self) -> list[dict]:
        rng, rows = self.rng, []
        for n, month in enumerate(_months()):
            growth = 1 + 0.012 * n                       # about 15% growth a year
            # Monthly advisory fees: 4 to 6 clients.
            for client in rng.sample(CLIENTS, rng.randint(4, 6)):
                due = month.replace(day=rng.choice([5, 10, 15, 20]))
                rows.append(self._row(REVENUE, f"Monthly advisory fee - {client}", due,
                                      rng.uniform(9_000, 20_000) * growth * self.scale,
                                      "rev-100", "cc-01", "acc-01", client, "ACH",
                                      partial_ok=True))
            # A consulting project in about half of the months.
            if rng.random() < 0.5:
                client = rng.choice(CLIENTS)
                due = month.replace(day=25)
                rows.append(self._row(REVENUE, f"Consulting project - {client}", due,
                                      rng.uniform(8_000, 30_000) * self.scale, "rev-110",
                                      "cc-02", "acc-01", client, "Wire"))
            # Fixed monthly expenses.
            for desc, cat, cc, vendor, low, high, day in FIXED_EXPENSES:
                account = "acc-02" if cat.startswith("exp-2") else "acc-01"
                rows.append(self._row(EXPENSE, f"{desc} - {month:%b %Y}", month.replace(day=day),
                                      rng.uniform(low, high) * self.scale * (growth if cat.startswith("exp-2") else 1),
                                      cat, cc, account, vendor, "ACH"))
            # Quarterly estimated income tax.
            if month.month in (1, 4, 6, 9):
                rows.append(self._row(EXPENSE, f"Estimated income tax - {month:%b %Y}",
                                      month.replace(day=15), rng.uniform(9_000, 16_000) * self.scale,
                                      "exp-400", "cc-03", "acc-01", "IRS", "EFTPS"))
            # One-off expenses.
            for _ in range(rng.randint(1, 3)):
                cat, _, vendor, low, high = rng.choice(ONE_OFF)
                cc = "cc-04" if cat in ("exp-330", "exp-340") else "cc-03"
                rows.append(self._row(EXPENSE, f"{vendor} - invoice", month.replace(day=rng.randint(1, 28)),
                                      rng.uniform(low, high) * self.scale, cat, cc, "acc-01",
                                      vendor, rng.choice(["Card", "ACH", "Check"])))
        # Owner contribution (cash in, not revenue).
        rows.append(self._row(REVENUE, "Owner contribution", date(2025, 3, 3), 50_000 * self.scale,
                              "tr-900", "", "acc-03", "Owners", "Wire"))
        self._plant_issues(rows)
        return rows

    def _plant_issues(self, rows):
        """Typical bookkeeping gaps, so the data checks have something to report."""
        past = [r for r in rows if r["due_date"] <= TODAY.isoformat()]
        for r in self.rng.sample(past, 6):
            r["category_id"] = ""
        for r in self.rng.sample([r for r in past if r["type"] == EXPENSE], 8):
            r["cost_center_id"] = ""
        for r in self.rng.sample([r for r in past if r["status"] == PAID], 4):
            r["account_id"] = ""

    def categories(self) -> list[dict]:
        return [{"company": self.company_code, "id": c, "name": n, "type": t, "parent_id": p,
                 "pnl_group": g, "in_pnl": bool(g)} for c, n, t, p, g in CATEGORIES]

    def cost_centers(self) -> list[dict]:
        return [{"company": self.company_code, "id": i, "name": n, "code": c, "active": True}
                for i, n, c in COST_CENTERS]

    def accounts(self) -> list[dict]:
        return [{"company": self.company_code, "id": i, "name": n, "type": t, "bank": b,
                 "active": True, "is_default": d,
                 "balance": round(self.rng.uniform(40_000, 250_000) * self.scale, 2)}
                for i, n, t, b, d in ACCOUNTS]
