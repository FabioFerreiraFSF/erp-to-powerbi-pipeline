"""
conta_azul.py - Connector for Conta Azul, a cloud ERP used by Brazilian small businesses.

Reads receivables, payables, categories, cost centers and bank accounts through
the Conta Azul REST API (OAuth 2.0), and maps the API's Portuguese field names
to the pipeline's English schema.

Log in once per company with `python -m pipeline.auth <CODE>`.

API rules handled here (enforced by Conta Azul from 2026-11-10, error 400 after):
  - date filters accept at most 365 days between "de" and "ate", so long
    histories are split into windows and merged, deduplicated by id;
  - tamanho_pagina accepts only 10, 20, 50, 100, 200, 500 or 1000;
  - the due date filter is required on receivables and payables searches.
The search endpoints do not return the bank account, payment method or payment
date, so each installment's detail is fetched in parallel to fill them in.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

from .. import auth, config
from ..schema import EXPENSE, OPEN, OVERDUE, PAID, PARTIAL, REVENUE

API = "https://api-v2.contaazul.com/v1"
PAGE_SIZE = 100                  # must be one of VALID_PAGE_SIZES
VALID_PAGE_SIZES = {10, 20, 50, 100, 200, 500, 1000}
MAX_WINDOW_DAYS = 364            # 365 days counting both ends
MAX_ATTEMPTS = 6
DETAIL_WORKERS = 10              # parallel installment lookups, safe for the rate limit
ENDPOINTS = {
    REVENUE: "/financeiro/eventos-financeiros/contas-a-receber/buscar",
    EXPENSE: "/financeiro/eventos-financeiros/contas-a-pagar/buscar",
    "installment": "/financeiro/eventos-financeiros/parcelas/{id}",
    "categories": "/categorias",
    "cost_centers": "/centro-de-custo",
    "accounts": "/conta-financeira",
    "balance": "/conta-financeira/{id}/saldo-atual",
}


# Conta Azul status codes -> schema status
_STATUS = {
    "ACQUITTED": PAID, "RECEBIDO": PAID, "PAGO": PAID, "QUITADO": PAID,
    "RECEBIDO_PARCIAL": PARTIAL, "PAGO_PARCIAL": PARTIAL, "PARTIAL": PARTIAL,
    "ATRASADO": OVERDUE, "OVERDUE": OVERDUE,
    "EM_ABERTO": OPEN, "PENDING": OPEN,
}


def _get(obj, *keys, default=""):
    """Safe nested lookup: _get(r, "cliente", "nome")."""
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key, default)
    return default if obj is None else obj


def _first(items):
    """Conta Azul returns lists of categories / cost centers; the report uses the first one."""
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0].get("id", "")
    return ""


def normalize_transaction(raw: dict, company: str, kind: str) -> dict:
    """One receivable (kind=REVENUE) or payable (kind=EXPENSE) from the API -> schema row."""
    party = "cliente" if kind == REVENUE else "fornecedor"
    status = str(_get(raw, "status")).upper()
    return {
        "id": _get(raw, "id"),
        "company": company,
        "type": kind,
        "description": _get(raw, "descricao"),
        "due_date": str(_get(raw, "data_vencimento"))[:10],
        "accrual_date": str(_get(raw, "data_competencia"))[:10],
        "payment_date": str(_get(raw, "data_pagamento"))[:10],
        "status": _STATUS.get(status, OPEN),
        "amount": _get(raw, "total", default=0),
        "amount_paid": _get(raw, "pago", default=0),
        "amount_open": _get(raw, "nao_pago", default=0),
        "category_id": _first(_get(raw, "categorias")),
        "cost_center_id": _first(_get(raw, "centros_de_custo")),
        "account_id": _get(raw, "conta_financeira_id"),
        "counterparty_id": _get(raw, party, "id"),
        "counterparty_name": _get(raw, party, "nome"),
        "payment_method": _get(raw, "metodo_pagamento"),
        "created_at": _get(raw, "data_criacao"),
        "updated_at": _get(raw, "data_alteracao"),
    }


def normalize_category(raw: dict, company: str) -> dict:
    kind = REVENUE if str(_get(raw, "tipo")).upper() in ("RECEITA", "REVENUE") else EXPENSE
    in_pnl = bool(_get(raw, "entrada_dre", default=False))
    return {"company": company, "id": _get(raw, "id"), "name": _get(raw, "nome"), "type": kind,
            "parent_id": _get(raw, "categoria_pai"), "in_pnl": in_pnl,
            "pnl_group": ("Revenue" if kind == REVENUE else "Operating Expenses") if in_pnl else ""}


def normalize_cost_center(raw: dict, company: str) -> dict:
    return {"company": company, "id": _get(raw, "id"), "name": _get(raw, "nome"),
            "code": _get(raw, "codigo"), "active": _get(raw, "ativo", default=True)}


def normalize_account(raw: dict, company: str) -> dict:
    return {"company": company, "id": _get(raw, "id"), "name": _get(raw, "nome"),
            "type": _get(raw, "tipo"), "bank": _get(raw, "banco"),
            "active": _get(raw, "ativo", default=True), "is_default": _get(raw, "conta_padrao", default=False),
            "balance": _get(raw, "saldo_atual", default=0)}


def _shift_months(day: date, months: int) -> date:
    total = day.year * 12 + day.month - 1 + months
    return date(total // 12, total % 12 + 1, 1)


def windows(start: date, end: date, max_days: int = MAX_WINDOW_DAYS):
    """Splits [start, end] into back-to-back windows the API accepts."""
    while start <= end:
        stop = min(start + timedelta(days=max_days), end)
        yield start, stop
        start = stop + timedelta(days=1)


def installment_fields(detail: dict) -> dict:
    """Bank account, payment method and payment date from an installment's detail.
    The account is on the installment (planned) or on its first settlement (actual)."""
    settlements = detail.get("baixas") or []
    first = settlements[0] if settlements else {}
    account = detail.get("conta_financeira") or first.get("conta_financeira") or {}
    return {"conta_financeira_id": account.get("id", ""),
            "metodo_pagamento": detail.get("metodo_pagamento") or first.get("metodo_pagamento") or "",
            "data_pagamento": first.get("data_pagamento") or ""}


class ContaAzulConnector:
    """One company in Conta Azul: paging, date windows, retries and installment details."""

    def __init__(self, company: config.Company, session: requests.Session | None = None):
        if PAGE_SIZE not in VALID_PAGE_SIZES:
            raise ValueError(f"PAGE_SIZE must be one of {sorted(VALID_PAGE_SIZES)}")
        self.company = company
        self.company_code, self.company_name = company.code, company.name
        self.http = session or requests.Session()
        self.failed_details = 0

    def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(MAX_ATTEMPTS):
            resp = self.http.get(API + path, params=params, timeout=30,
                                 headers={"Authorization": f"Bearer {auth.access_token(self.company)}"})
            if resp.status_code == 429:                       # rate limited
                time.sleep(2 ** attempt)
            elif resp.status_code in (500, 502, 503, 504):    # API busy or down: wait longer on 503
                time.sleep(min(2 ** attempt * (10 if resp.status_code == 503 else 1), 120))
            else:
                resp.raise_for_status()
                return resp.json()
        raise RuntimeError(f"[{self.company_code}] {path} kept failing after {MAX_ATTEMPTS} attempts")

    def _get_all(self, path: str, params: dict | None = None) -> list[dict]:
        items, page = [], 1
        while True:
            body = self._get(path, {**(params or {}), "pagina": page, "tamanho_pagina": PAGE_SIZE})
            batch = body.get("itens", [])
            items += batch
            if not batch or len(items) >= body.get("itens_totais", 0):
                return items
            page += 1

    def _search(self, kind: str, start: date, end: date) -> list[dict]:
        """Receivables or payables by due date, one window at a time, deduplicated by id."""
        seen, without_id = {}, []
        extra = {"permite_apenas_filhos": False} if kind == REVENUE else {}
        for first, last in windows(start, end):
            for r in self._get_all(ENDPOINTS[kind], {"data_vencimento_de": first.isoformat(),
                                                     "data_vencimento_ate": last.isoformat(), **extra}):
                if r.get("id"):
                    seen[r["id"]] = r
                else:
                    without_id.append(r)
        return list(seen.values()) + without_id

    def _detail(self, installment_id: str) -> dict:
        try:
            return installment_fields(self._get(ENDPOINTS["installment"].format(id=installment_id)))
        except Exception:
            self.failed_details += 1       # keep going, but report it at the end
            return {}

    def _with_details(self, rows: list[dict]) -> list[dict]:
        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            details = list(pool.map(lambda r: self._detail(r["id"]) if r.get("id") else {}, rows))
        return [{**r, **d} for r, d in zip(rows, details)]

    def transactions(self) -> list[dict]:
        today = date.today()
        start = _shift_months(today, -config.MONTHS_BACK)
        end = _shift_months(today, config.MONTHS_AHEAD + 1) - timedelta(days=1)
        rows = [normalize_transaction(raw, self.company_code, kind)
                for kind in (REVENUE, EXPENSE)
                for raw in self._with_details(self._search(kind, start, end))]
        if self.failed_details:
            print(f"  [{self.company_code}] Warning: {self.failed_details} installment details "
                  "could not be read; their bank account and payment date are empty.")
        return rows

    def categories(self) -> list[dict]:
        return [normalize_category(r, self.company_code)
                for r in self._get_all(ENDPOINTS["categories"], {"permite_apenas_filhos": False})]

    def cost_centers(self) -> list[dict]:
        return [normalize_cost_center(r, self.company_code) for r in self._get_all(ENDPOINTS["cost_centers"])]

    def accounts(self) -> list[dict]:
        rows = []
        for raw in self._get_all(ENDPOINTS["accounts"]):
            try:
                balance = self._get(ENDPOINTS["balance"].format(id=raw["id"])).get("saldo_atual", 0)
            except Exception:
                balance = ""
            rows.append(normalize_account({**raw, "saldo_atual": balance}, self.company_code))
        return rows
