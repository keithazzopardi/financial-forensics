# Financial Forensics

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is not already installed. From the project directory, sync the dependencies declared in `pyproject.toml`:

```sh
uv sync
```

This creates the project environment, updates `uv.lock` if needed, and installs the dependencies declared in `pyproject.toml`. You do not need to install them separately with `pip`.

## Extract bank statement transactions to JSON

Put PDF files in `data/splitted`, then run:

```sh
uv run main.py
```

The script loads the cached `Qwen/Qwen3.5-4B` model locally, renders each PDF page, and extracts the statement fields and transactions. It writes one formatted JSON file per PDF under `data/splitted/json`, using the same filename stem as the PDF. Each JSON object contains the statement start date, end date, IBAN, and a `Transactions` array with each transaction's date, description, debit/credit operation, amount, and balance after. No `HF_TOKEN` or hosted inference service is used.

If the model is not in the Hugging Face cache yet, download it once with:

```sh
hf download Qwen/Qwen3.5-4B
```

Qwen3.5 requires the latest Transformers code. The project installs it from Hugging Face Transformers' `main` branch. Review each generated JSON against the original statement before relying on extracted financial values.

If `uv` is not on your shell's `PATH`, install it first or use the Python interpreter from the environment created by uv:

```sh
uv run python main.py
```

## Extract cheques to JSON

Put cheque-book PDF files in `data` and run:

```sh
uv run cheque_to_json.py
```

The script first saves each source page as a separate PDF under
`data/cheques/splitted`, then processes those split pages and writes one JSON array per
page under `data/cheques/json` (named after the split page PDF). Each entry contains
`ChequeNumber`, numeric `Amount`,
`Date` in `yyyy-mm-dd`, and `Payable`. The cheque date is taken from below the cheque;
the date written inside the cheque is ignored. `Payable` is left blank when the model's
confidence is below 70%. You can provide input and output folders explicitly:

Page splitting is controlled by `SPLIT_PDF_PAGES` in `cheque_to_json.py`. Set it to
`False` to process source PDFs directly.

```sh
uv run cheque_to_json.py data/cheques data/cheques/json
```

If dependencies changed, run `uv sync` from the project directory, then try `uv run main.py` again.
