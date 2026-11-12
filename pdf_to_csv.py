"""Extract table structure from text-based PDFs with Microsoft's Table Transformer."""

from __future__ import annotations

import csv
from pathlib import Path

import fitz
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForObjectDetection


MODEL_ID = "microsoft/table-transformer-structure-recognition"
TABLE_DETECTION_MODEL_ID = "microsoft/table-transformer-detection"


class PdfTableExtractor:
    """Detect table rows and columns, then place PDF text into CSV cells."""

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self.table_processor = AutoImageProcessor.from_pretrained(TABLE_DETECTION_MODEL_ID)
        self.table_model = AutoModelForObjectDetection.from_pretrained(TABLE_DETECTION_MODEL_ID)
        self.table_model.eval()
        self.processor = AutoImageProcessor.from_pretrained(model_id)
        self.model = AutoModelForObjectDetection.from_pretrained(model_id)
        self.model.eval()

    def extract_pdf(self, pdf_path: Path, output_path: Path) -> int:
        """Write detected tables to CSV and return the number of extracted rows."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rows_written = 0

        with fitz.open(pdf_path) as pdf, output_path.open(
            "w", newline="", encoding="utf-8-sig"
        ) as csv_file:
            writer = csv.writer(csv_file)

            for page_number, page in enumerate(pdf, start=1):
                # Render at 150 DPI for table-structure recognition.
                pixmap = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                page_rows = self._extract_page_rows(page, image)

                if page_rows:
                    writer.writerow([f"Page {page_number}"])
                    writer.writerows(page_rows)
                    rows_written += len(page_rows)

        if rows_written == 0:
            raise ValueError(
                f"No tables with selectable text were extracted from {pdf_path}. "
                "Scanned PDFs need OCR, and table layouts may need a document-specific parser."
            )
        return rows_written

    def _extract_page_rows(self, page: fitz.Page, image: Image.Image) -> list[list[str]]:
        inputs = self.table_processor(images=image, return_tensors="pt")
        with torch.inference_mode():
            outputs = self.table_model(**inputs)

        target_sizes = torch.tensor([[image.height, image.width]])
        detections = self.table_processor.post_process_object_detection(
            outputs, threshold=0.7, target_sizes=target_sizes
        )[0]

        page_rows: list[list[str]] = []
        for label_id, box in zip(detections["labels"].tolist(), detections["boxes"].tolist()):
            label = self.table_model.config.id2label[label_id].lower()
            if "table" not in label:
                continue
            x0, y0, x1, y1 = (int(round(value)) for value in box)
            x0, x1 = max(0, x0), min(image.width, x1)
            y0, y1 = max(0, y0), min(image.height, y1)
            if x1 <= x0 or y1 <= y0:
                continue
            table_image = image.crop((x0, y0, x1, y1))
            page_rows.extend(self._extract_table_rows(page, table_image, (x0, y0), image.size))
        return page_rows

    def _extract_table_rows(
        self,
        page: fitz.Page,
        image: Image.Image,
        offset: tuple[int, int],
        page_image_size: tuple[int, int],
    ) -> list[list[str]]:
        inputs = self.processor(images=image, return_tensors="pt")
        with torch.inference_mode():
            outputs = self.model(**inputs)

        target_sizes = torch.tensor([[image.height, image.width]])
        detections = self.processor.post_process_object_detection(
            outputs, threshold=0.5, target_sizes=target_sizes
        )[0]

        row_boxes: list[tuple[float, float, float, float]] = []
        column_boxes: list[tuple[float, float, float, float]] = []
        for label_id, box in zip(detections["labels"].tolist(), detections["boxes"].tolist()):
            label = self.model.config.id2label[label_id].lower()
            coords = tuple(float(value) for value in box)
            if "row" in label:
                row_boxes.append(coords)
            elif "column" in label:
                column_boxes.append(coords)

        if not row_boxes or not column_boxes:
            return []

        # Model boxes are in rendered-image pixels; PDF word boxes are in points.
        scale_x = page.rect.width / page_image_size[0]
        scale_y = page.rect.height / page_image_size[1]
        offset_x, offset_y = offset
        row_boxes = [
            (x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y)
            for x0, y0, x1, y1 in row_boxes
        ]
        column_boxes = [
            (x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y)
            for x0, y0, x1, y1 in column_boxes
        ]
        row_boxes.sort(key=lambda box: (box[1] + box[3]) / 2)
        column_boxes.sort(key=lambda box: (box[0] + box[2]) / 2)

        words = page.get_text("words", sort=True)
        table: list[list[str]] = []
        for x0, y0, x1, y1 in row_boxes:
            cells = [[] for _ in column_boxes]
            row_center = (y0 + y1) / 2
            for word in words:
                wx0, wy0, wx1, wy1, text = word[:5]
                word_x = (wx0 + wx1) / 2 / scale_x
                word_y = (wy0 + wy1) / 2 / scale_y
                if not (y0 <= word_y <= y1):
                    continue
                for column_index, (cx0, cy0, cx1, cy1) in enumerate(column_boxes):
                    if cx0 <= word_x <= cx1 and cy0 <= row_center <= cy1:
                        cells[column_index].append((wx0, text))
                        break

            if any(cell for cell in cells):
                table.append([
                    " ".join(text for _, text in sorted(cell, key=lambda item: item[0]))
                    for cell in cells
                ])
        return table


def convert_folder(input_dir: Path, output_dir: Path) -> None:
    pdf_files = sorted(path for path in input_dir.glob("*.pdf") if path.is_file())
    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return

    extractor = PdfTableExtractor()
    for pdf_path in pdf_files:
        csv_path = output_dir / f"{pdf_path.stem}.csv"
        try:
            count = extractor.extract_pdf(pdf_path, csv_path)
        except ValueError as error:
            print(f"Skipped {pdf_path.name}: {error}")
            if csv_path.exists():
                csv_path.unlink()
            continue
        print(f"Saved {count} table rows to {csv_path}")
