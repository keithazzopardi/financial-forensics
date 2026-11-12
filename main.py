from pathlib import Path
from pdf_to_json import convert_folder


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    path = Path('./data/splitted')
    convert_folder(path, path / 'json')


