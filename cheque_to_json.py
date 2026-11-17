"""Extract cheque details from the left side of PDF pages using local Qwen."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pymupdf
import torch
from PIL import Image
from transformers import AutoModelForMultimodalLM, AutoProcessor

from split_pdf import split_pdf


MODEL_ID = "Qwen/Qwen3.5-4B"
SPLIT_PDF_PAGES = True
PROMPT = """Extract every cheque visible in this image. This image is the left half of a
document; ignore anything that would be on the right half. For each cheque, read:
- cheque_number, printed directly below the cheque
- amount, printed directly below the cheque
- date, printed directly below the cheque (usually mm/dd/yyyy)
- payable, the payee full name on the cheque's first line, above the amount written in words. This can be one, two or three words. Often two words
- Ignore at all costs Mr Tarcisio & Ms Maria Victoria Azzopardi.

In each pdf there are 4 cheques that needs to be exported. These have rectangular shape. 
Do not use the handwritten date inside the cheque. Do not confuse the amount in digits
below the cheque with the amount in words inside it. Do not invent unclear values.
Estimate payable_confidence from 0 to 1 based on how clearly the payee can be read.
Return JSON only in this shape:
{"cheques":[{"cheque_number":"000490","amount":"5642.31",
"date":"6/6/2019","payable":"Lands Authority","payable_confidence":0.95}]}
Use an empty string for any unreadable field and an empty cheques list if no cheque is
visible. Return one object per cheque, in top-to-bottom order."""


def load_model() -> tuple[Any, Any]:
    """Load the same locally cached multimodal model used by pdf_to_json.py."""
    if torch.backends.mps.is_available():
        device = torch.device("mps")
        dtype = torch.float16
    else:
        device = torch.device("cpu")
        dtype = torch.float32

    try:
        processor = AutoProcessor.from_pretrained(MODEL_ID, local_files_only=True)
        model = AutoModelForMultimodalLM.from_pretrained(
            MODEL_ID, torch_dtype=dtype, local_files_only=True
        ).to(device)
    except OSError as error:
        raise RuntimeError(
            f"Could not find {MODEL_ID} in the Hugging Face cache. Download it first with: "
            f"hf download {MODEL_ID}"
        ) from error
    model.eval()
    print(f"Loaded {MODEL_ID} on {device}")
    return processor, model


def parse_model_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"Model did not return JSON: {text}") from error
        return json.loads(text[start : end + 1])


def normalize_date(value: Any) -> str:
    """Convert the date below a cheque from mm/dd/yyyy to yyyy-mm-dd."""
    raw = str(value or "").strip()
    for date_format in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, date_format).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def normalize_amount(value: Any) -> float | int | str:
    raw = str(value or "").strip().replace(",", "").replace("€", "").strip()
    raw = re.sub(r"[^0-9.\-]", "", raw)
    try:
        number = float(raw)
    except ValueError:
        return ""
    return int(number) if number.is_integer() else number


def extract_page(processor: Any, model: Any, page: pymupdf.Page) -> list[dict[str, Any]]:
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png"))).convert("RGB")
    # Cheques occupy the left side; exclude statement details on the right.
    image = image.crop((0, 0, image.width // 2, image.height))
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image}, {"type": "text", "text": PROMPT}
    ]}]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, enable_thinking=False,
        tokenize=True, return_dict=True, return_tensors="pt",
    ).to(model.device)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=2048, do_sample=False)
    generated = output[0][inputs["input_ids"].shape[-1]:]
    result = parse_model_json(processor.decode(generated, skip_special_tokens=True))

    if isinstance(result, list):
        raw_cheques = result
    elif isinstance(result, dict):
        raw_cheques = result.get("cheques", [])
    else:
        raise ValueError(f"Expected a JSON object or list, got {type(result).__name__}")
    if not isinstance(raw_cheques, list):
        raise ValueError("Expected the model's 'cheques' value to be a list")

    cheques = []
    for cheque in raw_cheques:
        if not isinstance(cheque, dict):
            continue
        try:
            confidence = float(cheque.get("payable_confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0
        cheques.append({
            "ChequeNumber": str(cheque.get("cheque_number", "") or "").strip(),
            "Amount": normalize_amount(cheque.get("amount")),
            "Date": normalize_date(cheque.get("date")),
            "Payable": str(cheque.get("payable", "") or "").strip()
            if confidence >= 0.70 else "",
        })
    return cheques


def convert_pdf(processor: Any, model: Any, pdf_path: Path, output_path: Path) -> int:
    if SPLIT_PDF_PAGES:
        pages_dir = pdf_path.parent / "splitted"
        split_pdf(str(pdf_path.parent), pdf_path.name, str(pages_dir.resolve()))
        page_pdfs = sorted(pages_dir.glob(f"{pdf_path.stem}_page_*.pdf"))
    else:
        page_pdfs = [pdf_path]

    total_cheques = 0
    for page_pdf in page_pdfs:
        with pymupdf.open(page_pdf) as pdf:
            for page_number, page in enumerate(pdf, start=1):
                try:
                    cheques = extract_page(processor, model, page)
                except Exception as error:
                    print(
                        f"Failed {page_pdf}, page {page_number}: "
                        f"{type(error).__name__}: {error}"
                    )
                    continue

                if SPLIT_PDF_PAGES:
                    page_output = output_path.parent / f"{page_pdf.stem}.json"
                elif len(pdf) > 1:
                    page_output = output_path.parent / f"{pdf_path.stem}_page_{page_number}.json"
                else:
                    page_output = output_path
                page_output.parent.mkdir(parents=True, exist_ok=True)
                with page_output.open("w", encoding="utf-8") as json_file:
                    json.dump(cheques, json_file, indent=2, ensure_ascii=False)
                    json_file.write("\n")
                total_cheques += len(cheques)
                print(f"Saved {len(cheques)} cheques to {page_output}")
    return total_cheques

def convert_all(input_dir: Path | str, output_dir: Path | str) -> None:
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return
    processor, model = load_model()
    for index, pdf_path in enumerate(pdf_files, start=1):
        print(f"Processing PDF {index}/{len(pdf_files)}: {pdf_path}")
        output_path = output_dir / f"{pdf_path.stem}.json"
        try:
            count = convert_pdf(processor, model, pdf_path, output_path)
            print(f"Finished {pdf_path}: {count} cheques extracted")
        except Exception as error:
            print(f"Failed to process {pdf_path}: {type(error).__name__}: {error}")

if __name__ == "__main__":
    input_dir = "data/cheques"
    split_pdf(
        input_dir, 'scanned_cheques.pdf',
        'splitted')
    convert_all(input_dir, "data/cheques/json")
