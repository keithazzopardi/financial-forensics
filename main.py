from pathlib import Path
from pdf_to_json import convert_folder_pdf_to_json


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    path = Path('./data/splitted')
    convert_folder_pdf_to_json(path, path / 'json')


