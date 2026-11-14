"""Combine extracted bank statement JSON files into one CSV per IBAN."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


TRANSACTION_FIELDS = ("Date", "Description", "Operation", "Amount", "Balance after")
CSV_FIELDS = ("IBAN", "Start date", "End Date", *TRANSACTION_FIELDS, "Source file")
EXCLUDED_JSON_PREFIXES = ("11.2026.6_page_1",)
IBAN_REPAIRS = {
    "MT80VALL2201300000004001999971": "MT80VALL22013000000040019999971",
    "11111111111111111111": "MT88VALL22013000000017000277017",
    "MT96VALL22000000000000000000": "40011498700",
    "1100026758034234505": "40011498700",
    "1100016036632232547": "12411632055",
    "1100016036632564035": "12411632055",
    "1112411632055": "12411632055",
    "1000267580": "12411632055",
    "1411632055": "12411632055",
    "11000027668": "40011498700",
    "11000160366": "40011498700",
    "400001234567890123": "40011498700",
    "4552401309059784": "40011498700",
    "4552401301208546": "12411632055",
    "500116557427167": "50016989440",
    "400011498700": "MT35VALL22013000000012411632055",
    "MT40011498700": "40011498700",
    "MT40000000000000000000": "40011498700",
    "MT0011498700": "40011498700",
    "MT00011498700": "40011498700",
    "MT12345678901234567890": "40011498700",
    "MT40000240000000000000000": "40011498700",
    "MT110000000000000000": "12411632055",
    "MT4110002280543687438899990607": "12411632055",
    "MT04VALL22013000000050016989440": "50016989440",
    "MT06VALL22013000000040013563413":"40013563413",
    "MT20VALL22013000000050021149385": "50021149385",
    "MT35VALL22013000000012411632055": "12411632055",
    "MT96VALL22013000000040011498700": "40011498700",
    "1411632026": "12411632026",
    "5016989440": "50016989440",
    "500169899440": "50016989440"
}


def repair_iban(iban: str) -> str:
    """Apply repairs with or without an extracted MT prefix, then normalize."""
    iban = iban.strip().upper()
    if iban in IBAN_REPAIRS:
        return IBAN_REPAIRS[iban]
    # Some statements include MT on values whose repair entry omits the prefix.
    without_country_prefix = iban.removeprefix("MT")
    for known_iban, replacement in IBAN_REPAIRS.items():
        if known_iban.removeprefix("MT") == without_country_prefix:
            return replacement
    if iban.startswith("MT") and "VALL" not in iban:
        return iban[2:]
    return iban


def _transaction_datetime(value: Any) -> tuple[datetime, str]:
    """Parse supported statement date formats; unparseable dates sort last."""
    date_text = str(value or "").strip()
    for date_format in ("%d.%m.%Y", "%d %b %y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_text, date_format), date_text
        except ValueError:
            continue
    return datetime.max, date_text


def _safe_filename(value: str) -> str:
    """Keep output filenames portable while retaining the IBAN where possible."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "unknown_iban"


def convert_json_folder_to_csv(input_dir: Path, output_dir: Path) -> int:
    """Write a transaction CSV per IBAN; return the number of CSV files written."""
    files_by_iban: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for json_path in sorted(input_dir.rglob("*.json")):
        if json_path.stem.startswith(EXCLUDED_JSON_PREFIXES):
            print(f"Skipping excluded JSON file {json_path}")
            continue
        try:
            with json_path.open(encoding="utf-8") as source:
                statement = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            print(f"Skipping {json_path}: {error}")
            continue
        if not isinstance(statement, dict):
            print(f"Skipping {json_path}: expected a JSON object")
            continue
        iban = repair_iban(str(statement.get("IBAN") or ""))
        if not iban:
            print(f"Skipping {json_path}: no IBAN")
            continue
        files_by_iban[iban].append((json_path, statement))

    output_dir.mkdir(parents=True, exist_ok=True)
    for iban, statements in sorted(files_by_iban.items()):
        output_path = output_dir / f"{_safe_filename(iban)}.csv"
        with output_path.open("w", newline="", encoding="utf-8-sig") as destination:
            writer = csv.DictWriter(destination, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for json_path, statement in statements:
                transactions = statement.get("Transactions", []) or []
                if not isinstance(transactions, list):
                    print(f"Skipping transactions in {json_path}: expected an array")
                    continue
                valid_transactions = [
                    transaction for transaction in transactions
                    if isinstance(transaction, dict)
                ]
                valid_transactions.sort(key=lambda transaction: _transaction_datetime(
                    transaction.get("Date")
                ))
                for transaction in valid_transactions:
                    writer.writerow({
                        "IBAN": iban,
                        "Start date": statement.get("Start date", ""),
                        "End Date": statement.get("End Date", ""),
                        **{field: transaction.get(field, "") for field in TRANSACTION_FIELDS},
                        "Source file": json_path.name,
                    })
        print(f"Saved {output_path}")
    return len(files_by_iban)


if __name__ == "__main__":
    source_dir = Path("data/splitted/json")
    destination_dir = Path("data/splitted/csv")
    if convert_json_folder_to_csv(source_dir, destination_dir) == 0:
        print(f"No statements with an IBAN found in {source_dir}")
