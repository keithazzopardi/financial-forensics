# Financial Forensics

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is not already installed. From the project directory, sync the dependencies declared in `pyproject.toml`:

```sh
uv sync
```

This creates the project environment, updates `uv.lock` if needed, and installs the dependencies declared in `pyproject.toml`. You do not need to install them separately with `pip`.

## Run

Put the PDF files you want to split in the `data` directory, then run:

```sh
uv run main.py
```

The script writes one PDF per page into `data`, with filenames in the form `original_name_page_1.pdf`.

If `uv` is not on your shell's `PATH`, install it first or use the Python interpreter from the environment created by uv:

```sh
uv run python main.py
```

If you see `ModuleNotFoundError: No module named 'PyPDF2'`, run `uv sync` from the project directory, then try `uv run main.py` again. The project declares the `pypdf2` distribution that provides the `PyPDF2` import.
