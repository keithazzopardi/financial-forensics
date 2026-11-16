"""Collect AUTOTRF transfers and cautiously associate cheque entries."""

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
AUTOTRF_TARGET_RE = re.compile(r"\bAUTOTRF\s+([A-Z0-9]+)", re.IGNORECASE)
CHEQUE_RE = re.compile(r"^\s*CHEQUE\s+(?:(\d+)\b|(WITHDRAWAL)\b)", re.IGNORECASE)
MATCH_FIELDS = (
    "Cheque match type",
    "Matched cheque description",
    "Matched cheque date",
    "Matched cheque amount",
    "Matched cheque fee",
    "Cheque amount difference",
)


def _amount(value: str | None) -> Decimal | None:
    try:
        return Decimal((value or "").replace(",", "").strip())
    except InvalidOperation:
        return None


def _date(value: str | None) -> date | None:
    text = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%d%b%y", "%d%b%Y", "%Y-%m-%d", "%d %b %y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _column(fieldnames: list[str] | None, name: str) -> str | None:
    if not fieldnames:
        return None
    normalized = name.strip().casefold()
    return next((field for field in fieldnames if field.strip().casefold() == normalized), None)


def _read_statement_rows(input_dir: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    """Read CSV statement rows recursively and group them by their own account IBAN."""
    all_rows: list[dict[str, str]] = []
    by_account: dict[str, list[dict[str, str]]] = {}
    for csv_path in sorted(input_dir.rglob("*.csv")):
        try:
            with csv_path.open("r", newline="", encoding="utf-8-sig") as source:
                reader = csv.DictReader(source)
                fields = list(reader.fieldnames or [])
                required = {name: _column(fields, name) for name in
                            ("IBAN", "Description", "Date", "Amount", "Operation")}
                if not all(required.values()):
                    print(f"Skipping {csv_path}: missing transaction columns")
                    continue
                for line_number, row in enumerate(reader, start=2):
                    row["_account"] = row.get(required["IBAN"] or "", "").strip()
                    row["_description"] = row.get(required["Description"] or "", "")
                    row["_date"] = row.get(required["Date"] or "", "")
                    row["_amount"] = row.get(required["Amount"] or "", "")
                    row["_operation"] = row.get(required["Operation"] or "", "")
                    row["_source"] = row.get("Source file", "")
                    row["_path"] = str(csv_path)
                    row["_line"] = str(line_number)
                    row["_balance"] = row.get(_column(fields, "Balance after") or "", "")
                    row["_fields"] = "\x1f".join(fields)
                    all_rows.append(row)
                    by_account.setdefault(row["_account"], []).append(row)
        except (OSError, UnicodeError, csv.Error) as error:
            print(f"Skipping {csv_path}: {error}")
    return all_rows, by_account


def _fee_balance_support(transfer: dict[str, str], cheque: dict[str, str]) -> bool:
    """Check whether the transfer and fee rows' closing balances reconcile."""
    transfer_balance = _amount(transfer.get("_balance"))
    cheque_balance = _amount(cheque.get("_balance"))
    fee = _amount(cheque.get("_amount"))
    operation = transfer.get("_operation", "").strip().casefold()
    if None in (transfer_balance, cheque_balance, fee):
        return False
    expected = transfer_balance - fee if operation == "credit" else transfer_balance + fee
    return abs(expected - cheque_balance) <= Decimal("0.02")


def _find_matches(rows: list[dict[str, str]], by_account: dict[str, list[dict[str, str]]]) -> dict[int, tuple[dict[str, str], str]]:
    """Return only one-to-one cheque links supported by amount/date or fee evidence."""
    transfers = [row for row in rows if AUTOTRF_TARGET_RE.search(row.get("_description", ""))]
    cheque_candidates: list[tuple[dict[str, str], str]] = []
    for account_rows in by_account.values():
        for row in account_rows:
            m = CHEQUE_RE.match(row.get("_description", ""))
            amount = _amount(row.get("_amount"))
            if (m and row.get("_operation", "").strip().casefold() == "debit"
                    and amount is not None and _date(row.get("_date")) is not None):
                kind = ("numbered cheque fee" if m.group(1) and amount <= Decimal("5")
                        else "cheque withdrawal")
                # Small numbered CHEQUE entries are retained as fee references;
                # cheque withdrawals and larger numbered entries are principals.
                if m.group(2) or amount > Decimal("5") or (m.group(1) and amount > 0):
                    cheque_candidates.append((row, kind))

    possibilities: dict[int, list[tuple[dict[str, str], str, Decimal]]] = {}
    for transfer_index, transfer in enumerate(transfers):
        transfer_date = _date(transfer.get("_date"))
        transfer_amount = _amount(transfer.get("_amount"))
        target = AUTOTRF_TARGET_RE.search(transfer.get("_description", ""))
        target_account = target.group(1) if target else ""
        # Cheques are matched against the statement rows belonging to the account
        # on which the cheque was presented, not the transfer's opposite side.
        account = transfer.get("_account", "")
        possible = []
        if transfer_date and transfer_amount is not None:
            for cheque, kind in cheque_candidates:
                if cheque.get("_account") != account:
                    continue
                cheque_date = _date(cheque.get("_date"))
                cheque_amount = _amount(cheque.get("_amount"))
                if not cheque_date or cheque_amount is None:
                    continue
                day_gap = (cheque_date - transfer_date).days
                if kind == "numbered cheque fee":
                    # A fee records the cheque number, not its face value. Require
                    # the same date and either a unique same-day pair or a balance
                    # transition that corroborates the association.
                    if day_gap != 0 or cheque.get("_account") != account:
                        continue
                    same_day_transfers = [r for r in by_account.get(account, [])
                                          if AUTOTRF_TARGET_RE.search(r.get("_description", ""))
                                          and _date(r.get("_date")) == transfer_date]
                    same_day_fees = [c for c, ck in cheque_candidates
                                     if ck == "numbered cheque fee" and c.get("_account") == account
                                     and _date(c.get("_date")) == transfer_date]
                    if _fee_balance_support(transfer, cheque) or (len(same_day_transfers) == 1 and len(same_day_fees) == 1):
                        possible.append((cheque, kind, abs(transfer_amount - cheque_amount)))
                elif 0 <= day_gap <= 1 and abs(transfer_amount - cheque_amount) <= Decimal("1"):
                    possible.append((cheque, kind, abs(transfer_amount - cheque_amount)))
        possibilities[transfer_index] = possible

    usage: dict[tuple[str, str], int] = {}
    for possible in possibilities.values():
        if len(possible) == 1:
            cheque = possible[0][0]
            key = (cheque.get("_path", ""), cheque.get("_line", ""))
            usage[key] = usage.get(key, 0) + 1
    result = {}
    for index, possible in possibilities.items():
        if len(possible) != 1:
            continue
        cheque, kind, difference = possible[0]
        key = (cheque.get("_path", ""), cheque.get("_line", ""))
        if usage.get(key) == 1:
            result[index] = (cheque, kind)
    return result


def collect_autotrf_transactions(input_dir: Path, output_path: Path) -> int:
    """Write AUTOTRF rows with original fields and any unambiguous cheque link."""
    rows, by_account = _read_statement_rows(input_dir)
    transfers = [row for row in rows if AUTOTRF_TARGET_RE.search(row.get("_description", ""))]
    found = _find_matches(rows, by_account)

    output_fields: list[str] = []
    for row in transfers:
        for field in row.get("_fields", "").split("\x1f"):
            if field and field.strip().casefold() not in {"start date", "end date"} and field not in output_fields:
                output_fields.append(field)
    added_fields = (*MATCH_FIELDS, ORIGIN_FIELD, TARGET_FIELD, SOURCE_FIELD)
    resolved_fields = []
    for field in added_fields:
        name, suffix = field, 2
        while name in output_fields:
            name = f"{field} {suffix}"
            suffix += 1
        output_fields.append(name)
        resolved_fields.append(name)
    match_columns = resolved_fields[:len(MATCH_FIELDS)]
    origin_column, target_column, source_column = resolved_fields[-3:]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as destination:
        writer = csv.DictWriter(destination, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()
        for index, transfer in enumerate(transfers):
            fields = transfer.get("_fields", "").split("\x1f")
            desc_col, iban_col = _column(fields, "Description"), _column(fields, "IBAN")
            out = {key: transfer.get(key, "") for key in fields}
            out[origin_column] = transfer.get(iban_col or "", "")
            target = AUTOTRF_TARGET_RE.search(transfer.get(desc_col or "", ""))
            out[target_column] = target.group(1) if target else ""
            out[source_column] = transfer.get("Source file", "")
            if index in found:
                cheque, kind = found[index]
                cheque_desc = cheque.get("_description", "")
                cheque_amount = cheque.get("_amount", "")
                if kind == "numbered cheque fee":
                    out[match_columns[0]] = kind
                    out[match_columns[1]] = cheque_desc
                    out[match_columns[2]] = cheque.get("_date", "")
                    out[match_columns[4]] = cheque_amount
                else:
                    transfer_amount = _amount(transfer.get("_amount"))
                    cheque_amount_value = _amount(cheque_amount)
                    out[match_columns[0]] = kind
                    out[match_columns[1]] = cheque_desc
                    out[match_columns[2]] = cheque.get("_date", "")
                    out[match_columns[3]] = cheque_amount
                    if transfer_amount is not None and cheque_amount_value is not None:
                        out[match_columns[5]] = str(abs(transfer_amount - cheque_amount_value))
            writer.writerow(out)

    print(f"Saved {output_path} ({len(transfers)} AUTOTRF transactions, {len(found)} unambiguous cheque matches)")
    return len(transfers)


if __name__ == "__main__":
    if not collect_autotrf_transactions(DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_PATH):
        print(f"No AUTOTRF transactions found in {DEFAULT_INPUT_DIR}")
