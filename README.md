# Financial Forensics

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is not already installed. From the project directory, sync the dependencies declared in `pyproject.toml`:

```sh
uv sync
```

This creates the project environment, updates `uv.lock` if needed, and installs the dependencies declared in `pyproject.toml`. You do not need to install them separately with `pip`.

## Extract PDF tables to CSV

Put text-based PDF files with tables in the `data` directory, then run:

```sh
uv run main.py
```

The script uses Microsoft's Hugging Face Table Transformer models to locate tables and detect their rows and columns, then uses selectable PDF text to populate the cells. It writes one CSV per source PDF under `data/csv`. The models download on first use and are cached by Hugging Face.

Scanned PDFs do not contain selectable text, so this version reports that no table rows could be extracted. They need an OCR step before the text can be placed into CSV cells. Table layouts with merged cells or irregular formatting may also need document-specific handling.

If `uv` is not on your shell's `PATH`, install it first or use the Python interpreter from the environment created by uv:

```sh
uv run python main.py
```

If dependencies changed, run `uv sync` from the project directory, then try `uv run main.py` again.
