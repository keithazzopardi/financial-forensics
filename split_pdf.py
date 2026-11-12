from PyPDF2 import PdfReader, PdfWriter
from pathlib import Path

def split_pdf(folder_path: str, file_name: str, output_folder: str | None = None):
    input_path: Path = Path(folder_path) / file_name
    output_dir: Path = Path(folder_path) / output_folder if output_folder is not None else Path(folder_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf = PdfReader(input_path)
    for page in range(len(pdf.pages)):
        pdf_writer = PdfWriter()
        pdf_writer.add_page(pdf.pages[page])

        output_filename = output_dir / f"{input_path.stem}_page_{page + 1}.pdf"
        with open(output_filename, 'wb') as out:
            pdf_writer.write(out)

    print('Splitted: {}'.format(file_name))

def read_all_and_split_pdf(path: Path):
    pdf_files = sorted(
        file.name for file in path.iterdir()
        if file.is_file() and file.suffix.lower() == '.pdf'
    )

    for file_name in pdf_files:
        split_pdf(str(path), file_name, 'splitted')