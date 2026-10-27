"""
render_preview.py - Builds an HTML preview of the three report pages from the
pipeline's CSV output, so the README can show the dashboard without Power BI.

    python -m pipeline --demo
    python scripts/render_preview.py            # writes docs/preview.html
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

DATA = Path(sys.argv[1] if len(sys.argv) > 1 else "data_powerbi")
OUT = Path(__file__).resolve().parent.parent / "docs" / "preview.html"
YEAR, LAST_MONTH = "2026", 9          # year to date through September
MONTHS = [f"{YEAR}-{m:02d}" for m in range(1, LAST_MONTH + 1)]


def read(name):
    with (DATA / f"{name}.csv").open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def money(v, short=True):
    if abs(v) < 0.5:
        return "-"
    if short and abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if short and abs(v) >= 1_000:
        return f"${v / 1_000:.0f}k"
    return f"${v:,.0f}" if v >= 0 else f"(${-v:,.0f})"


def bars(series_a, series_b, labels, name_a, name_b):
    """Grouped bar chart as inline SVG."""
    w, h, pad = 820, 220, 24
    top = max(max(series_a), max(series_b)) * 1.1
    group = (w - 2 * pad) / len(labels)
    bw = group * 0.34
    parts = []
    for i, (a, b, label) in enumerate(zip(series_a, series_b, labels)):
        x = pad + i * group + group * 0.14
        for j, (v, color) in enumerate(((a, "#38B449"), (b, "#C9D3CB"))):
            bh = v / top * (h - 30)
            parts.append(f'<rect x="{x + j * (bw + 3):.1f}" y="{h - 20 - bh:.1f}" width="{bw:.1f}" '
                         f'height="{bh:.1f}" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{x + bw:.1f}" y="{h - 4}" font-size="11" fill="#5A5A5A" '
                     f'text-anchor="middle">{label}</text>')
    legend = (f'<span class="dot" style="background:#38B449"></span>{name_a}'
              f'<span class="dot" style="background:#C9D3CB;margin-left:14px"></span>{name_b}')
    return f'<svg viewBox="0 0 {w} {h}" width="100%">{"".join(parts)}</svg><div class="legend">{legend}</div>'


def main():
    facts, cats = read("fact_transactions"), read("dim_category")
    accounts, issues = read("dim_account"), read("data_quality")
    cat = {(c["company"], c["id"]): c for c in cats}

    pnl = defaultdict(float)                   # (group, category name, month) -> amount
    rev, exp = defaultdict(float), defaultdict(float)
    cash_in, cash_out = defaultdict(float), defaultdict(float)
    for r in facts:
        month = r["accrual_date"][:7]
        c = cat.get((r["company"], r["category_id"]))
        if c and c["in_pnl"] == "True" and month in MONTHS:
            amount = float(r["amount"])
            pnl[(c["pnl_group"], c["name"], month)] += amount
            (rev if c["type"] == "revenue" else exp)[month] += amount
        paid_month = r["payment_date"][:7]
        if paid_month in MONTHS:
            (cash_in if r["type"] == "revenue" else cash_out)[paid_month] += float(r["amount_paid"])

    labels = [f"{m[5:]}" for m in MONTHS]
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    labels = [month_names[int(m) - 1] for m in labels]
    total_rev, total_exp = sum(rev.values()), sum(exp.values())
    result = total_rev - total_exp

    # P&L matrix
    order = ["Revenue", "Other Income", "Cost of Services", "Operating Expenses", "Taxes"]
    rows_html = []
    for g in order:
        names = sorted({n for (gg, n, _) in pnl if gg == g})
        for n in names:
            sign = 1 if g in ("Revenue", "Other Income") else -1
            vals = [sign * pnl[(g, n, m)] for m in MONTHS]
            cells = "".join(f'<td class="num {"neg" if v < 0 else ""}">{money(v, False)}</td>' for v in vals)
            rows_html.append(f'<tr><td>{n}</td><td><span class="pill {"pos" if sign > 0 else "negp"}">'
                             f'{g}</span></td>{cells}<td class="num"><b>{money(sum(vals), False)}</b></td></tr>')
    res_cells = "".join(f'<td class="num">{money(rev[m] - exp[m], False)}</td>' for m in MONTHS)
    head = "".join(f"<th class='num'>{l}</th>" for l in labels)

    # Cash flow
    net = sum(cash_in.values()) - sum(cash_out.values())
    balance = sum(float(a["balance"]) for a in accounts)
    open_ar = sum(float(r["amount_open"]) for r in facts if r["type"] == "revenue" and r["due_date"] <= f"{YEAR}-10-15")
    overdue = sum(float(r["amount_open"]) for r in facts if r["status"] == "overdue")

    # Data checks
    by_check = defaultdict(int)
    for i in issues:
        by_check[i["detail"]] += 1
    check_rows = "".join(f"<tr><td>{i['company']}</td><td>{i['description']}</td><td>{i['detail']}</td>"
                         f"<td class='num'>{i['due_date']}</td><td class='num'>{money(float(i['amount']), False)}</td></tr>"
                         for i in sorted(issues, key=lambda i: i["due_date"], reverse=True)[:9])
    check_cards = "".join(f'<div class="kpi warn"><div class="k">{d}</div><div class="v">{n}</div></div>'
                          for d, n in sorted(by_check.items(), key=lambda x: -x[1]))

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Northwind - Finance Dashboard</title>
<style>
body{{margin:0;font-family:'DejaVu Sans',Arial,sans-serif;background:#EAEEE9;color:#2D2D2D}}
.page{{width:1400px;padding:22px 28px;box-sizing:border-box}}
.nav{{background:#2D2D2D;color:#fff;height:52px;display:flex;align-items:center;padding:0 28px;gap:16px;font-size:14px}}
.nav b{{color:#7ED990;font-size:16px;margin-right:18px}} .tab{{padding:6px 14px;border-radius:6px;color:#bbb}} .tab.on{{background:#1E7A2C;color:#fff}}
h1{{font-size:21px;margin:4px 0 2px}} .sub{{color:#5A5A5A;font-size:12px;margin-bottom:16px}}
.row{{display:flex;gap:14px;margin-bottom:14px}} .card{{background:#fff;border-radius:10px;padding:16px 18px;box-shadow:0 2px 8px rgba(0,0,0,.06);flex:1}}
.kpi{{background:#fff;border-radius:10px;padding:14px 18px;flex:1;border-left:4px solid #38B449;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.kpi.red{{border-color:#E53935}} .kpi.warn{{border-color:#FF8C00}} .k{{font-size:11px;letter-spacing:.6px;color:#5A5A5A;text-transform:uppercase}} .v{{font-size:26px;font-weight:bold;margin-top:6px}}
.t{{font-size:12px;font-weight:bold;letter-spacing:.6px;text-transform:uppercase;margin-bottom:8px}}
table{{width:100%;border-collapse:collapse;font-size:12px}} th{{background:#1E7A2C;color:#fff;padding:7px 8px;text-align:left;font-size:11px}}
td{{padding:6px 8px;border-bottom:1px solid #E8E8E8}} .num{{text-align:right;font-family:'DejaVu Sans Mono',monospace}} .neg{{color:#C62828}}
tr.total td{{background:#38B449;color:#fff;font-weight:bold}} .pill{{font-size:10px;padding:2px 7px;border-radius:9px}} .pos{{background:#E3F5E6;color:#1E7A2C}} .negp{{background:#FDECEA;color:#C62828}}
.legend{{font-size:11px;color:#5A5A5A}} .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}}
</style></head><body>
<div id="pnl"><div class="nav"><b>Northwind Advisory Group</b><span class="tab on">P&amp;L</span><span class="tab">Cash Flow</span><span class="tab">Data Checks</span></div>
<div class="page"><h1>Profit &amp; Loss</h1><div class="sub">All companies · accrual basis · {YEAR} year to date (Jan-Sep) · fictional data</div>
<div class="row"><div class="kpi"><div class="k">Revenue YTD</div><div class="v">{money(total_rev)}</div></div>
<div class="kpi red"><div class="k">Expenses YTD</div><div class="v">{money(total_exp)}</div></div>
<div class="kpi"><div class="k">Operating result</div><div class="v">{money(result)}</div></div>
<div class="kpi"><div class="k">Operating margin</div><div class="v">{result / total_rev:.1%}</div></div></div>
<div class="row"><div class="card"><div class="t">Revenue vs. expenses by month</div>{bars([rev[m] for m in MONTHS], [exp[m] for m in MONTHS], labels, "Revenue", "Expenses")}</div></div>
<div class="card"><div class="t">P&amp;L by category and month</div><table><tr><th>Category</th><th>Group</th>{head}<th class="num">YTD</th></tr>
{''.join(rows_html)}<tr class="total"><td>Operating result</td><td></td>{res_cells}<td class="num">{money(result, False)}</td></tr></table></div></div></div>

<div id="cash"><div class="nav"><b>Northwind Advisory Group</b><span class="tab">P&amp;L</span><span class="tab on">Cash Flow</span><span class="tab">Data Checks</span></div>
<div class="page"><h1>Cash Flow</h1><div class="sub">All companies · by payment date · {YEAR} (Jan-Sep) · fictional data</div>
<div class="row"><div class="kpi"><div class="k">Cash in</div><div class="v">{money(sum(cash_in.values()))}</div></div>
<div class="kpi red"><div class="k">Cash out</div><div class="v">{money(sum(cash_out.values()))}</div></div>
<div class="kpi"><div class="k">Net cash flow</div><div class="v">{money(net)}</div></div>
<div class="kpi"><div class="k">Bank balance today</div><div class="v">{money(balance)}</div></div>
<div class="kpi warn"><div class="k">Overdue to collect or pay</div><div class="v">{money(overdue)}</div></div></div>
<div class="card"><div class="t">Cash in vs. cash out by month</div>{bars([cash_in[m] for m in MONTHS], [cash_out[m] for m in MONTHS], labels, "Cash in", "Cash out")}</div></div></div>

<div id="checks"><div class="nav"><b>Northwind Advisory Group</b><span class="tab">P&amp;L</span><span class="tab">Cash Flow</span><span class="tab on">Data Checks</span></div>
<div class="page"><h1>Data Checks</h1><div class="sub">Entries to fix in the ERP before closing the month · fictional data</div>
<div class="row">{check_cards}</div>
<div class="card"><div class="t">Latest issues</div><table><tr><th>Company</th><th>Description</th><th>Issue</th><th class="num">Due date</th><th class="num">Amount</th></tr>{check_rows}</table></div></div></div>
</body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"Preview written to {OUT}")


if __name__ == "__main__":
    main()
