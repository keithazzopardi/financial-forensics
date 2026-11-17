from pathlib import Path

import pymupdf


def split_pdf(folder_path: str, file_name: str, output_folder: str | None = None):
    input_path: Path = Path(folder_path) / file_name
    output_dir: Path = Path(folder_path) / output_folder if output_folder is not None else Path(folder_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    with pymupdf.open(input_path) as pdf:
        for page_number in range(len(pdf)):
            page_pdf = pymupdf.open()
            page_pdf.insert_pdf(pdf, from_page=page_number, to_page=page_number)
            output_filename = output_dir / f"{input_path.stem}_page_{page_number + 1}.pdf"
            page_pdf.save(output_filename)
            page_pdf.close()

    print('Splitted: {}'.format(file_name))

def read_all_and_split_pdf(path: Path):
    pdf_files = sorted(
        file.name for file in path.iterdir()
        if file.is_file() and file.suffix.lower() == '.pdf'
    )

    for file_name in pdf_files:
        split_pdf(str(path), file_name, 'splitted')
