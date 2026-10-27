"""Tests for the sample ERP, the Conta Azul mapping, the data checks and a full demo run."""

import csv
import os
import subprocess
import sys
from pathlib import Path

from pipeline.checks import completeness, run_checks
from pipeline.connectors.conta_azul import normalize_category, normalize_transaction
from pipeline.connectors.sample import SampleConnector
from pipeline.schema import EXPENSE, FACT_TRANSACTIONS, OVERDUE, PAID, PARTIAL, REVENUE

ROOT = Path(__file__).resolve().parent.parent


def test_sample_data_is_repeatable_and_complete():
    first, second = SampleConnector("NWA").transactions(), SampleConnector("NWA").transactions()
    assert first == second                                   # fixed seed: same data every run
    assert all(set(FACT_TRANSACTIONS) <= set(r) for r in first)
    assert {r["type"] for r in first} == {REVENUE, EXPENSE}


def test_sample_amounts_add_up():
    for r in SampleConnector("NWC").transactions():
        assert round(r["amount_paid"] + r["amount_open"], 2) == r["amount"]
        if r["status"] == PAID:
            assert r["payment_date"] and r["amount_open"] == 0


def test_checks_find_the_planted_issues():
    rows = SampleConnector("NWA").transactions()
    found = {i["check"] for i in run_checks(rows)}
    assert {"missing_category", "missing_cost_center", "missing_bank_account"} <= found
    assert all(0 <= share <= 100 for share in completeness(rows).values())


def test_check_rules():
    base = {"id": "1", "company": "X", "type": EXPENSE, "description": "", "due_date": "2026-01-01",
            "amount": 10, "category_id": "c", "cost_center_id": "cc", "account_id": "a",
            "counterparty_name": "Vendor", "status": PAID}
    assert run_checks([base]) == []
    assert [i["check"] for i in run_checks([{**base, "status": PARTIAL, "account_id": ""}])] == \
        ["missing_bank_account"]
    assert [i["check"] for i in run_checks([{**base, "status": OVERDUE}])] == ["overdue"]
    revenue_without_cc = {**base, "type": REVENUE, "cost_center_id": ""}
    assert run_checks([revenue_without_cc]) == []           # cost center is only required on expenses


def test_conta_azul_mapping():
    raw = {
        "id": "abc", "descricao": "Aluguel", "data_vencimento": "2026-05-10T00:00:00",
        "data_competencia": "2026-05-01", "status": "RECEBIDO_PARCIAL", "total": 1000.0,
        "pago": 400.0, "nao_pago": 600.0, "categorias": [{"id": "cat-1", "nome": "Rent"}],
        "centros_de_custo": [], "fornecedor": {"id": "f1", "nome": "Landlord Co"},
    }
    row = normalize_transaction(raw, "NWA", EXPENSE)
    assert row["status"] == PARTIAL and row["due_date"] == "2026-05-10"
    assert (row["category_id"], row["cost_center_id"], row["counterparty_name"]) == ("cat-1", "", "Landlord Co")
    assert row["payment_date"] == ""                          # missing field -> empty, not an error

    cat = normalize_category({"id": "c", "nome": "Vendas", "tipo": "RECEITA", "entrada_dre": True}, "NWA")
    assert (cat["type"], cat["in_pnl"], cat["pnl_group"]) == (REVENUE, True, "Revenue")


def test_demo_run_writes_every_table(tmp_path):
    out = subprocess.run([sys.executable, "-m", "pipeline", "--demo", "--output", str(tmp_path)],
                         cwd=ROOT, capture_output=True, text=True, check=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT)}).stdout
    assert "Issues to fix in the ERP" in out
    for name in ["fact_transactions", "dim_category", "dim_cost_center", "dim_account",
                 "dim_company", "dim_date", "data_quality"]:
        with (tmp_path / f"{name}.csv").open(encoding="utf-8-sig") as f:
            assert len(list(csv.DictReader(f))) > 0, name


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _FakeSession:
    """Answers like the Conta Azul API: 250 receivables in pages of 100, one 429 on the way."""

    def __init__(self):
        self.calls = []

    def get(self, url, params, headers, timeout):
        self.calls.append(params["pagina"])
        if len(self.calls) == 2:
            return _FakeResponse(429, {})
        start = (params["pagina"] - 1) * 100
        items = [{"id": str(i), "status": "EM_ABERTO", "total": 10} for i in range(start, min(start + 100, 250))]
        return _FakeResponse(200, {"itens": items, "itens_totais": 250})


def test_connector_pages_and_retries(monkeypatch):
    from pipeline import auth, config
    from pipeline.connectors import conta_azul
    monkeypatch.setattr(auth, "access_token", lambda company: "token")
    monkeypatch.setattr(conta_azul.time, "sleep", lambda s: None)
    session = _FakeSession()
    connector = conta_azul.ContaAzulConnector(config.Company("NWA", "Northwind"), session)
    rows = connector._get_all(conta_azul.ENDPOINTS[REVENUE])
    assert len(rows) == 250 and session.calls == [1, 2, 2, 3]


def test_token_is_refreshed_when_expired(tmp_path, monkeypatch):
    import json
    from pipeline import auth, config
    monkeypatch.setattr(config, "TOKENS_DIR", tmp_path)
    company = config.Company("NWA", "Northwind", "id", "secret")
    company.token_file.write_text(json.dumps({"access_token": "old", "refresh_token": "r1",
                                              "expires_in": 3600, "saved_at": 0}))
    sent = {}

    def fake_token_request(c, data):
        sent.update(data)
        return {"access_token": "new", "expires_in": 3600, "saved_at": 10**10}
    monkeypatch.setattr(auth, "_token_request", fake_token_request)
    assert auth.access_token(company) == "new"
    assert sent == {"grant_type": "refresh_token", "refresh_token": "r1"}
    assert json.loads(company.token_file.read_text())["refresh_token"] == "r1"   # kept when not resent
    assert auth.code_from_url("http://127.0.0.1:5000/callback?code=abc&state=x") == "abc"


def test_date_windows_respect_the_365_day_limit():
    from datetime import date
    from pipeline.connectors.conta_azul import windows
    parts = list(windows(date(2024, 1, 1), date(2026, 12, 31)))
    assert parts[0][0] == date(2024, 1, 1) and parts[-1][1] == date(2026, 12, 31)
    assert all((b - a).days <= 364 for a, b in parts)
    assert all((parts[i + 1][0] - parts[i][1]).days == 1 for i in range(len(parts) - 1))   # no gaps, no overlap


def test_installment_detail_fields():
    from pipeline.connectors.conta_azul import installment_fields
    settled = {"baixas": [{"conta_financeira": {"id": "acc-9"}, "data_pagamento": "2026-03-02",
                           "metodo_pagamento": "PIX"}]}
    assert installment_fields(settled) == {"conta_financeira_id": "acc-9", "metodo_pagamento": "PIX",
                                           "data_pagamento": "2026-03-02"}
    planned = {"conta_financeira": {"id": "acc-1"}, "metodo_pagamento": "BOLETO"}
    assert installment_fields(planned)["conta_financeira_id"] == "acc-1"
    assert installment_fields(planned)["data_pagamento"] == ""
