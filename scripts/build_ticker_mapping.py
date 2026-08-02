"""Regenerates data/tickers.json from vnstock's full symbol listing.

Requires internet access. The repo already ships a seed file with ~45
well-known tickers so the app works out of the box; run this script when
you want the mapping to cover the full listing instead.

Usage:
    python scripts/build_ticker_mapping.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resolvers.text_utils import strip_legal_prefix  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "tickers.json"


def _short_alias(full_name: str) -> str:
    return strip_legal_prefix(full_name.strip().lower())


# Popular brand names that don't derive cleanly from stripping the legal-entity
# prefix off the official name (e.g. "VNM" -> "Vinamilk", not "Sữa Việt Nam").
# Merged in on top of the auto-generated aliases for better fuzzy matching.
WELL_KNOWN_ALIASES: dict[str, list[str]] = {
    "VNM": ["vinamilk"],
    "HPG": ["hoa phat"],
    "VCB": ["vietcombank"],
    "TCB": ["techcombank"],
    "CTG": ["vietinbank"],
    "BID": ["bidv"],
    "GAS": ["pv gas"],
    "POW": ["pv power"],
    "PLX": ["petrolimex"],
    "VND": ["vndirect"],
    "STB": ["sacombank"],
    "HDB": ["hdbank"],
    "VPB": ["vpbank"],
    "TPB": ["tpbank"],
    "MBB": ["mbbank"],
    "HSG": ["hoa sen"],
    "PVS": ["ptsc"],
    "SAB": ["sabeco", "bia sai gon"],
    "HVN": ["vietnam airlines"],
    "NVL": ["novaland"],
    "FRT": ["fpt retail"],
    "DHG": ["duoc hau giang"],
}


def build_mapping() -> list[dict]:
    from vnstock.api.listing import Listing

    df = Listing(source="vci").all_symbols()

    records = []
    for _, row in df.iterrows():
        ticker = str(row.get("symbol") or "").strip().upper()
        full_name = str(row.get("organ_name") or "").strip()
        if not ticker or not full_name:
            continue
        alias = _short_alias(full_name)
        aliases = [alias] if alias and alias != full_name.lower() else []
        aliases.extend(a for a in WELL_KNOWN_ALIASES.get(ticker, []) if a not in aliases)
        records.append(
            {
                "ticker": ticker,
                "full_name": full_name,
                "short_name": alias.title() if alias else full_name,
                "exchange": "",
                "aliases": aliases,
            }
        )
    return records


def main() -> None:
    records = build_mapping()
    OUTPUT_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi {len(records)} mã vào {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
