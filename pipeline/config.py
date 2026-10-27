"""
config.py - Settings for the pipeline.

Each company of the group has its own API credentials in companies/<CODE>.json
(NOT versioned). Copy companies/EXAMPLE.json.example to start:

    {"code": "NWA", "name": "Northwind Advisory LLC",
     "client_id": "...", "client_secret": "..."}

OAuth tokens are saved in tokens/<CODE>.json (also NOT versioned).
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_DIR = ROOT / "companies"
TOKENS_DIR = ROOT / "tokens"
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "data_powerbi"))

# OAuth redirect: local only. Register exactly this URL in the ERP developer portal.
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://127.0.0.1:5000/callback")

# How many months of history to export (and how far ahead, for open bills).
MONTHS_BACK = int(os.environ.get("MONTHS_BACK", "24"))
MONTHS_AHEAD = int(os.environ.get("MONTHS_AHEAD", "12"))


@dataclass
class Company:
    code: str
    name: str
    client_id: str = ""
    client_secret: str = ""

    @property
    def token_file(self) -> Path:
        return TOKENS_DIR / f"{self.code}.json"


def load_companies() -> list[Company]:
    """All companies with a credentials file in companies/."""
    companies = []
    for path in sorted(COMPANIES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        companies.append(Company(**data))
    return companies
