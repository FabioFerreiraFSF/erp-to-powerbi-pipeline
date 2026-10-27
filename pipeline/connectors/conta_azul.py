"""
conta_azul.py - Connector for Conta Azul, a cloud ERP used by Brazilian small businesses.

Reads receivables, payables, categories, cost centers and bank accounts through
the Conta Azul REST API (OAuth 2.0), and maps the API's Portuguese field names
to the pipeline's English schema.

Log in once per company with `python -m pipeline.auth <CODE>`.
"""

import time
from datetime import date

import requests

from .. import auth, config
from ..schema import EXPENSE, OPEN, OVERDUE, PAID, PARTIAL, REVENUE

API = "https://api-v2.contaazul.com/v1"
PAGE_SIZE = 100
ENDPOINTS = {
    REVENUE: "/financeiro/eventos-financeiros/contas-a-receber/buscar",
    EXPENSE: "/financeiro/eventos-financeiros/contas-a-pagar/buscar",
    "categories": "/categorias",
    "cost_centers": "/centro-de-custo",
    "accounts": "/conta-financeira",
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


class ContaAzulConnector:
    """One company in Conta Azul. Pages through every list and retries when rate limited."""

    def __init__(self, company: config.Company, session: requests.Session | None = None):
        self.company = company
        self.company_code, self.company_name = company.code, company.name
        self.http = session or requests.Session()

    def _get_all(self, path: str, params: dict | None = None) -> list[dict]:
        items, page = [], 1
        while True:
            query = {**(params or {}), "pagina": page, "tamanho_pagina": PAGE_SIZE}
            for attempt in range(5):
                resp = self.http.get(API + path, params=query, timeout=30,
                                     headers={"Authorization": f"Bearer {auth.access_token(self.company)}"})
                if resp.status_code != 429:
                    break
                time.sleep(2 ** attempt)                   # rate limited: wait and try again
            resp.raise_for_status()
            body = resp.json()
            batch = body.get("itens", []) if isinstance(body, dict) else body
            items += batch
            if len(batch) < PAGE_SIZE:
                return items
            page += 1

    def transactions(self) -> list[dict]:
        today = date.today()
        window = {"data_vencimento_de": _shift_months(today, -config.MONTHS_BACK).isoformat(),
                  "data_vencimento_ate": _shift_months(today, config.MONTHS_AHEAD + 1).isoformat()}
        return [normalize_transaction(raw, self.company_code, kind)
                for kind in (REVENUE, EXPENSE)
                for raw in self._get_all(ENDPOINTS[kind], window)]

    def categories(self) -> list[dict]:
        return [normalize_category(r, self.company_code) for r in self._get_all(ENDPOINTS["categories"])]

    def cost_centers(self) -> list[dict]:
        return [normalize_cost_center(r, self.company_code) for r in self._get_all(ENDPOINTS["cost_centers"])]

    def accounts(self) -> list[dict]:
        return [normalize_account(r, self.company_code) for r in self._get_all(ENDPOINTS["accounts"])]
