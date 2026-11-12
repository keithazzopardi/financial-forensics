"""Extract bank-statement transactions from PDF pages with local Dolphin-v2."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
import torch
from PIL import Image
from transformers import AutoModelForMultimodalLM, AutoProcessor


MODEL_ID = "ByteDance/Dolphin-v2"
STATEMENT_FIELDS = ("Start date", "End Date", "IBAN")
TRANSACTION_FIELDS = ("Date", "Description", "Operation", "Amount", "Balance after")
OCR_PROMPT = "Read text in the image."
STRUCTURE_PROMPT = """Convert this OCR text from a bank-statement page to valid JSON in exactly this shape:
{
  "statement": {"start_date": "", "end_date": "", "iban": ""},
  "transactions": [
    {"date": "", "description": "", "operation": "Debit or Credit", "amount": "", "balance_after": ""}
  ]
}
Use exactly Debit or Credit for operation based on the statement columns. Keep printed
dates and amounts. Combine wrapped description lines. Use empty strings for fields not
visible. Do not include account-holder details, opening/closing balance lines, or page
footers as transactions. The statement period is printed in a form like
"25 DEC 18 - 20 JUN 19": put the first date in start_date and the second in end_date.
The IBAN is a full Maltese IBAN, usually beginning with "MT96VALL22"; extract all of
its characters from the statement and never return only this example prefix. Do not
guess missing characters. Return only JSON."""


def load_model() -> tuple[Any, Any]:
    """Load the already-cached Hugging Face model without making network requests."""
    try:
        processor = AutoProcessor.from_pretrained(MODEL_ID, local_files_only=True)
        model = AutoModelForMultimodalLM.from_pretrained(
            MODEL_ID,
            torch_dtype="auto",
            device_map="auto",
            local_files_only=True,
        )
    except OSError as error:
        raise RuntimeError(
            f"Could not find {MODEL_ID} in the Hugging Face cache. Download it first with: "
            f"hf download {MODEL_ID}"
        ) from error
    model.eval()
    return processor, model


def _extract_json(text: str) -> dict[str, Any]:
    """Parse JSON even if the model adds a short markdown code fence."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    print(f"Dolphin structured response:\n{text}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"Dolphin did not return JSON. Raw response:\n{text}") from error
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as nested_error:
            raise ValueError(f"Dolphin returned invalid JSON. Raw response:\n{text}") from nested_error


def extract_page(
    processor: Any, model: Any, page: fitz.Page
) -> tuple[dict[str, str], list[dict[str, str]]]:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": OCR_PROMPT},
        ],
    }]
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=2048, do_sample=False)
    generated = output[0][inputs["input_ids"].shape[-1] :]
    ocr_text = processor.decode(generated, skip_special_tokens=True).strip()
    print(f"Dolphin OCR response:\n{ocr_text}")

    text_prompt = f"{STRUCTURE_PROMPT}\n\nOCR text:\n{ocr_text}"
    text_inputs = processor.tokenizer.apply_chat_template(
        [{"role": "user", "content": text_prompt}],
        add_generation_prompt=True,
        tokenize=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.inference_mode():
        structured_output = model.generate(
            **text_inputs,
            max_new_tokens=2048,
            do_sample=False,
        )
    structured_generated = structured_output[0][text_inputs["input_ids"].shape[-1] :]
    result = _extract_json(
        processor.tokenizer.decode(structured_generated, skip_special_tokens=True)
    )

    statement = result.get("statement", {}) or {}
    metadata = {
        field: str(statement.get(source, "") or "")
        for field, source in zip(STATEMENT_FIELDS, ("start_date", "end_date", "iban"))
    }
    transactions = [
        {
            field: str(transaction.get(source, "") or "")
            for field, source in zip(
                TRANSACTION_FIELDS,
                ("date", "description", "operation", "amount", "balance_after"),
            )
        }
        for transaction in result.get("transactions", [])
    ]
    return metadata, transactions


def convert_pdf(
    processor: Any, model: Any, pdf_path: Path, output_path: Path
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    statement = dict.fromkeys(STATEMENT_FIELDS, "")
    transactions: list[dict[str, str]] = []
    with fitz.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            try:
                page_statement, page_transactions = extract_page(processor, model, page)
            except Exception as error:
                raise RuntimeError(f"Failed to extract page {page_number} of {pdf_path}") from error
            for field in STATEMENT_FIELDS:
                if not statement[field] and page_statement[field]:
                    statement[field] = page_statement[field]
            transactions.extend(page_transactions)

    result = {**statement, "Transactions": transactions}
    with output_path.open("w", encoding="utf-8") as json_file:
        json.dump(result, json_file, indent=2, ensure_ascii=False)
        json_file.write("\n")
    return len(transactions)


def convert_folder(input_dir: Path, output_dir: Path) -> None:
    pdf_files = sorted(path for path in input_dir.glob("*.pdf") if path.is_file())
    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return

    processor, model = load_model()
    for pdf_path in pdf_files:
        json_path = output_dir / f"{pdf_path.stem}.json"
        count = convert_pdf(processor, model, pdf_path, json_path)
        print(f"Saved {count} transactions to {json_path}")
