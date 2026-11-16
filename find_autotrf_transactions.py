"""Collect automated transfer transactions from statement CSV files."""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path


DEFAULT_INPUT_DIR = Path("data/splitted/csv")
DEFAULT_OUTPUT_PATH = Path("data/splitted/cheques/autotrf_transactions.csv")
SOURCE_FIELD = "Source CSV file"
ORIGIN_FIELD = "Origin IBAN"
TARGET_FIELD = "Targeted IBAN"
TRANSFER_RE = re.compile(
    r"\bAUTOTRF\s+(?P<autotrf_target>[A-Z0-9]+)"
    r"|\bAUTOMATED\s+TRANSFER(?:\s+(?!REF\b)(?P<automated_target>[A-Z0-9]+))?",
    re.IGNORECASE,
)


def _date(value: str | None) -> date | None:
    text = (value or "").strip()
    for fmt in (
        "%d.%m.%Y",
        "%d%b%y",
        "%d%b%Y",
        "%Y-%m-%d",
        "%d %b %y",
        "%d %b %Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%y",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _output_date(value: str | None) -> str:
    parsed = _date(value)
    return parsed.isoformat() if parsed else (value or "")


def _column(fieldnames: list[str] | None, name: str) -> str | None:
    if not fieldnames:
        return None
    normalized = name.strip().casefold()
    return next((field for field in fieldnames if field.strip().casefold() == normalized), None)


def _transfer_match(description: str) -> re.Match[str] | None:
    """Match AUTOTRF or AUTOMATED TRANSFER and capture a target when present."""
    return TRANSFER_RE.search(description)


def _transfer_target(match: re.Match[str] | None) -> str:
    if not match:
        return ""
    return match.group("autotrf_target") or match.group("automated_target") or ""


def _read_statement_rows(input_dir: Path) -> list[dict[str, str]]:
    """Read CSV statement rows recursively."""
    all_rows: list[dict[str, str]] = []
    for csv_path in sorted(input_dir.rglob("*.csv")):
        try:
            with csv_path.open("r", newline="", encoding="utf-8-sig") as source:
                reader = csv.DictReader(source)
                fields = list(reader.fieldnames or [])
                required = {name: _column(fields, name) for name in ("IBAN", "Description", "Date")}
                if not all(required.values()):
                    print(f"Skipping {csv_path}: missing transaction columns")
                    continue
                for row in reader:
                    row["_description"] = row.get(required["Description"] or "", "")
                    row["_date"] = row.get(required["Date"] or "", "")
                    row["_fields"] = "\x1f".join(fields)
                    all_rows.append(row)
        except (OSError, UnicodeError, csv.Error) as error:
            print(f"Skipping {csv_path}: {error}")
    return all_rows


def collect_autotrf_transactions(input_dir: Path, output_path: Path) -> int:
    """Write automated transfer rows with their original transaction fields."""
    rows = _read_statement_rows(input_dir)
    transfers = [row for row in rows if _transfer_match(row.get("_description", ""))]
    transfers.sort(key=lambda row: _date(row.get("_date")) or date.min, reverse=True)

    output_fields: list[str] = []
    for row in transfers:
        for field in row.get("_fields", "").split("\x1f"):
            if (field and field.strip().casefold() not in {"iban", "start date", "end date"}
                    and field not in output_fields):
                output_fields.append(field)
    added_fields = (ORIGIN_FIELD, TARGET_FIELD, SOURCE_FIELD)
    resolved_fields = []
    for field in added_fields:
        name, suffix = field, 2
        while name in output_fields:
            name = f"{field} {suffix}"
            suffix += 1
        output_fields.append(name)
        resolved_fields.append(name)
    origin_column, target_column = resolved_fields[:2]
    source_column = resolved_fields[-1]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as destination:
        writer = csv.DictWriter(destination, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()
        for transfer in transfers:
            fields = transfer.get("_fields", "").split("\x1f")
            desc_col, iban_col = _column(fields, "Description"), _column(fields, "IBAN")
            out = {key: transfer.get(key, "") for key in fields}
            date_col = _column(fields, "Date")
            if date_col:
                out[date_col] = _output_date(transfer.get(date_col, ""))
            out[origin_column] = transfer.get(iban_col or "", "")
            target = _transfer_match(transfer.get(desc_col or "", ""))
            out[target_column] = _transfer_target(target)
            out[source_column] = transfer.get("Source file", "")
            writer.writerow(out)

    print(f"Saved {output_path} ({len(transfers)} automated transfer transactions)")
    return len(transfers)


if __name__ == "__main__":
    if not collect_autotrf_transactions(DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_PATH):
        print(f"No AUTOTRF transactions found in {DEFAULT_INPUT_DIR}")
