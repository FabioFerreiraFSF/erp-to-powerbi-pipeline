"""
ERP to Power BI pipeline - command line.

    python -m pipeline --demo            # fake ERP data, no login needed
    python -m pipeline                   # every company in companies/*.json
    python -m pipeline --company NWA     # one company only

Output folder (default data_powerbi/): the star schema CSVs for Power BI, plus
data_quality.csv with the entries to fix in the ERP. Point the Power BI template
at this folder and click Refresh.
"""

import argparse
import time
from collections import Counter
from pathlib import Path

from . import config
from .checks import DATA_QUALITY, completeness, run_checks
from .export import export_all, write_csv


def main():
    parser = argparse.ArgumentParser(description="Exports ERP data to CSVs for Power BI.")
    parser.add_argument("--demo", action="store_true", help="use the fake sample ERP")
    parser.add_argument("--company", help="export only this company code")
    parser.add_argument("--output", default=str(config.OUTPUT_DIR), help="output folder")
    args = parser.parse_args()

    start = time.time()
    if args.demo:
        from .connectors.sample import COMPANIES, SampleConnector
        codes = [args.company] if args.company else list(COMPANIES)
        connectors = [SampleConnector(code) for code in codes]
    else:
        from .connectors.conta_azul import ContaAzulConnector
        companies = [c for c in config.load_companies()
                     if not args.company or c.code == args.company]
        if not companies:
            raise SystemExit("No company found. Add a credentials file to companies/ "
                             "(see companies/EXAMPLE.json.example) or run with --demo.")
        connectors = [ContaAzulConnector(c) for c in companies]

    output = Path(args.output)
    tables = export_all(connectors, output)

    issues = run_checks(tables["fact_transactions"])
    write_csv(output / "data_quality.csv", issues, DATA_QUALITY)

    print("\nData quality (share of entries with the field filled in):")
    for field, share in completeness(tables["fact_transactions"]).items():
        print(f"  {field:<24} {share:6.1f}%")
    by_check = Counter(i["check"] for i in issues)
    print("Issues to fix in the ERP: " + (", ".join(f"{n} {c}" for c, n in by_check.items()) or "none"))
    print(f"\nDone in {time.time() - start:.1f}s. Open Power BI and click Refresh.")


if __name__ == "__main__":
    main()
