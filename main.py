from pathlib import Path
from split_pdf import read_all_and_split_pdf
from pdf_to_csv import convert_folder


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    path = Path('./data/splitted')
    convert_folder(path, path / 'csv')


