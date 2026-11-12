from PyPDF2 import PdfReader, PdfWriter
from os import listdir
from os.path import isfile, join


def print_log(name):
    print(f'{name}')  # Press ⌘F8 to toggle the breakpoint.


def split_pdf(folder_path, file_name):
    pdf = PdfReader(folder_path+'/'+file_name)
    for page in range(len(pdf.pages)):
        pdf_writer = PdfWriter()
        pdf_writer.add_page(pdf.pages[page])

        output_filename: str = "pdf_forms/splitted/{}_page_{}.pdf".format(file_name.replace('.pdf', ''), page + 1)

    with open(output_filename, 'wb') as out:
        pdf_writer.write(out)

    print('Created: {}'.format(output_filename))

    print_log('Split file')


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
     path: str =  './data'
     onlyfiles = [f for f in listdir(path) if isfile(join(path, f))]

    for file_name in onlyfiles:
        split_pdf(path, file_name)



