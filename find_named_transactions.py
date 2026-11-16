"""Collect transactions mentioning selected people from all CSV files."""

from __future__ import annotations

import csv
import re
from pathlib import Path


PEOPLE = (
    "MARYSE",
    "ALESSANDRO",
    "DIANE",
    "KEITH",
    "NICOLE",
    "ELVIN"
)
DEFAULT_INPUT_DIR = Path("data/splitted/csv")
DEFAULT_OUTPUT_DIR = Path("data/splitted/person_transactions")
SOURCE_FIELD = "Source CSV file"


def _description_field(fieldnames: list[str] | None) -> str | None:
    """Find the Description column without depending on its capitalization."""
    if not fieldnames:
        return None
    return next((name for name in fieldnames if name.strip().casefold() == "description"), None)


def collect_transactions(input_dir: Path, output_dir: Path) -> int:
    """Write one CSV per person and return the total number of matches."""
    matches: dict[str, list[tuple[dict[str, str], list[str]]]] = {
        person: [] for person in PEOPLE
    }
    csv_paths = sorted(path for path in input_dir.rglob("*.csv") if path.is_file())

    for csv_path in csv_paths:
        try:
            with csv_path.open("r", newline="", encoding="utf-8-sig") as source:
                reader = csv.DictReader(source)
                description_column = _description_field(reader.fieldnames)
                if description_column is None:
                    print(f"Skipping {csv_path}: no Description column")
                    continue
                fields = list(reader.fieldnames or [])
                for row in reader:
                    description = row.get(description_column) or ""
                    for person in PEOPLE:
                        if person.casefold() in description.casefold():
                            matches[person].append((row, fields))
        except (OSError, UnicodeError, csv.Error) as error:
            print(f"Skipping {csv_path}: {error}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for person in PEOPLE:
        # Include the source filename as a distinct field while retaining every
        # transaction field from the original CSV.
        source_fields = next(
            (fields for _, fields in matches[person]), []
        )
        output_fields = list(source_fields)
        source_column = SOURCE_FIELD
        suffix = 2
        while source_column in output_fields:
            source_column = f"{SOURCE_FIELD} {suffix}"
            suffix += 1
        output_fields.append(source_column)

        output_path = output_dir / f"{re.sub(r'[^A-Za-z0-9]+', '_', person).strip('_').lower()}.csv"
        with output_path.open("w", newline="", encoding="utf-8-sig") as destination:
            writer = csv.DictWriter(destination, fieldnames=output_fields)
            writer.writeheader()
            for row, _ in matches[person]:
                writer.writerow({**row, source_column: row.get("Source file") or ""})
        print(f"Saved {output_path} ({len(matches[person])} transactions)")

    return sum(len(rows) for rows in matches.values())


if __name__ == "__main__":
    total = collect_transactions(DEFAULT_INPUT_DIR, DEFAULT_OUTPUT_DIR)
    if not total:
        print(f"No matching transactions found in {DEFAULT_INPUT_DIR}")
