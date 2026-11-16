"""Collect automated transfer transactions from statement CSV files."""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


DEFAULT_INPUT_DIR = Path("data/splitted/csv")
DEFAULT_OUTPUT_PATH = Path("data/splitted/cheques/autotrf_transactions.csv")
SOURCE_FIELD = "Source CSV file"
ORIGIN_FIELD = "Origin IBAN"
TARGET_FIELD = "Targeted IBAN"
CHEQUE_NUMBER_FIELD = "Cheque Number"
TRANSFER_RE = re.compile(
    r"\bAUTOTRF\s+(?P<autotrf_target>[A-Z0-9]+)"
    r"|\bAUTOMATED\s+TRANSFER(?:\s+(?!REF\b)(?P<automated_target>[A-Z0-9]+))?",
    re.IGNORECASE,
)
REFERENCE_RE = re.compile(
    r"\bAUTOMATED\s+TRANSFER(?:\s+[A-Z0-9]+)?\s+REF:\s*([^-]+?)\s*-",
    re.IGNORECASE,
)
CHEQUE_WITHDRAWAL_RE = re.compile(r"^\s*CHEQUE\s+WITHDRAWAL\s+000(\d+)\b", re.IGNORECASE)


def _amount_key(value: str | None) -> Decimal | None:
    try:
        return Decimal((value or "").replace(",", "").strip()).normalize()
    except InvalidOperation:
        return None


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


def _rows_match_amount(left: dict[str, str], right: dict[str, str]) -> bool:
    """Require a known transaction amount to match before linking rows."""
    left_fields = left.get("_fields", "").split("\x1f")
    right_fields = right.get("_fields", "").split("\x1f")
    left_amount = _amount_key(left.get(_column(left_fields, "Amount") or "", ""))
    right_amount = _amount_key(right.get(_column(right_fields, "Amount") or "", ""))
    return left_amount is not None and left_amount == right_amount


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
                for line_number, row in enumerate(reader, start=1):
                    row["_description"] = row.get(required["Description"] or "", "")
                    row["_date"] = row.get(required["Date"] or "", "")
                    row["_fields"] = "\x1f".join(fields)
                    row["_csv_path"] = str(csv_path)
                    row["_csv_line"] = str(line_number)
                    all_rows.append(row)
        except (OSError, UnicodeError, csv.Error) as error:
            print(f"Skipping {csv_path}: {error}")
    return all_rows


def collect_autotrf_transactions(input_dir: Path, output_path: Path) -> int:
    """Write automated transfer rows with their original transaction fields."""
    rows = _read_statement_rows(input_dir)
    transfers = [row for row in rows if _transfer_match(row.get("_description", ""))]

    # Pair reciprocal reference transfers only when reference, transaction date,
    # and amount all agree and there is exactly one row for each of two IBANs.
    groups: dict[tuple[str, date, Decimal], list[int]] = {}
    for index, transfer in enumerate(transfers):
        description = transfer.get("_description", "")
        reference = REFERENCE_RE.search(description)
        fields = transfer.get("_fields", "").split("\x1f")
        date_col, amount_col = _column(fields, "Date"), _column(fields, "Amount")
        transaction_date = _date(transfer.get(date_col or "", ""))
        amount = _amount_key(transfer.get(amount_col or ""))
        if not reference or transaction_date is None or amount is None:
            continue
        key = (reference.group(1).strip().upper(), transaction_date, amount)
        groups.setdefault(key, []).append(index)

    grouped_target: dict[int, str] = {}
    grouped_counterpart: dict[int, dict[str, str]] = {}
    consumed: set[int] = set()
    for indices in groups.values():
        if len(indices) != 2:
            continue
        left_index, right_index = indices
        left, right = transfers[left_index], transfers[right_index]
        left_fields = left.get("_fields", "").split("\x1f")
        right_fields = right.get("_fields", "").split("\x1f")
        left_iban_col, right_iban_col = _column(left_fields, "IBAN"), _column(right_fields, "IBAN")
        left_iban = left.get(left_iban_col or "", "").strip()
        right_iban = right.get(right_iban_col or "", "").strip()
        if not left_iban or not right_iban or left_iban == right_iban:
            continue
        left_target = _transfer_target(_transfer_match(left.get("_description", "")))
        right_target = _transfer_target(_transfer_match(right.get("_description", "")))
        # When targets are present, make sure the two rows point at each other.
        # Generic reference rows have no target and retain the existing pairing
        # behavior based on their distinct IBANs.
        if (left_target and left_target != right_iban) or (right_target and right_target != left_iban):
            continue
        grouped_target[left_index] = right_iban
        grouped_counterpart[left_index] = right
        consumed.add(right_index)

    output_transfers = [
        (transfer, grouped_target.get(index), grouped_counterpart.get(index))
        for index, transfer in enumerate(transfers)
        if index not in consumed
    ]
    output_transfers.sort(
        key=lambda item: _date(item[0].get("_date")) or date.min,
        reverse=True,
    )

    output_fields: list[str] = []
    for row, _, _ in output_transfers:
        for field in row.get("_fields", "").split("\x1f"):
            if (field and field.strip().casefold() not in {"iban", "start date", "end date"}
                    and field not in output_fields):
                output_fields.append(field)
    added_fields = (ORIGIN_FIELD, TARGET_FIELD, CHEQUE_NUMBER_FIELD, SOURCE_FIELD)
    resolved_fields = []
    for field in added_fields:
        name, suffix = field, 2
        while name in output_fields:
            name = f"{field} {suffix}"
            suffix += 1
        output_fields.append(name)
        resolved_fields.append(name)
    origin_column, target_column = resolved_fields[:2]
    cheque_number_column, source_column = resolved_fields[-2:]
    first_columns = {origin_column, target_column, cheque_number_column}
    output_fields = [origin_column, target_column] + [
        field for field in output_fields if field not in first_columns
    ]
    amount_column = _column(output_fields, "Amount")
    if amount_column:
        output_fields.insert(output_fields.index(amount_column) + 1, cheque_number_column)
    else:
        output_fields.append(cheque_number_column)
    row_lookup = {
        (row.get("_csv_path", ""), int(row.get("_csv_line", "0"))): row
        for row in rows
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as destination:
        writer = csv.DictWriter(destination, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()
        for transfer, paired_target, paired_counterpart in output_transfers:
            fields = transfer.get("_fields", "").split("\x1f")
            desc_col, iban_col = _column(fields, "Description"), _column(fields, "IBAN")
            out = {key: transfer.get(key, "") for key in fields}
            date_col = _column(fields, "Date")
            if date_col:
                out[date_col] = _output_date(transfer.get(date_col, ""))
            out[origin_column] = transfer.get(iban_col or "", "")
            target = _transfer_match(transfer.get(desc_col or "", ""))
            out[target_column] = paired_target or _transfer_target(target)
            for related_transfer in (transfer, paired_counterpart):
                if not related_transfer:
                    continue
                source_path = related_transfer.get("_csv_path", "")
                source_line = int(related_transfer.get("_csv_line", "0"))
                for neighbor_line in (source_line - 1, source_line + 1):
                    neighbor = row_lookup.get((source_path, neighbor_line))
                    if not neighbor:
                        continue
                    cheque = CHEQUE_WITHDRAWAL_RE.match(neighbor.get("_description", ""))
                    if cheque and _rows_match_amount(related_transfer, neighbor):
                        out[cheque_number_column] = f"Cheque {cheque.group(1)}"
                        break
                if out.get(cheque_number_column):
                    break
            out[source_column] = transfer.get("Source file", "")
            writer.writerow(out)

    print(f"Saved {output_path} ({len(output_transfers)} automated transfer transactions)")
    return len(output_transfers)


if __name__ == "__main__":
    if not collect_autotrf_transactions(DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_PATH):
        print(f"No AUTOTRF transactions found in {DEFAULT_INPUT_DIR}")
