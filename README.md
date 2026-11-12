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

The script loads the cached `ByteDance/Dolphin-v2` model locally, renders each PDF page, and extracts the statement fields and transactions. It writes one formatted JSON file per PDF under `data/splitted/json`, using the same filename stem as the PDF. Each JSON object contains the statement start date, end date, IBAN, and a `Transactions` array with each transaction's date, description, debit/credit operation, amount, and balance after. No `HF_TOKEN` or hosted inference service is used.

If the model is not in the Hugging Face cache yet, download it once with:

```sh
hf download ByteDance/Dolphin-v2
```

The Hugging Face model card currently identifies Dolphin-v2 as a 4B parameter BF16 model. The downloaded weights and memory needed at runtime can therefore exceed 2 GB; a 2 GB limit is not enough for this model in its standard form. Review the generated JSON against the original statement before relying on extracted financial values.

If `uv` is not on your shell's `PATH`, install it first or use the Python interpreter from the environment created by uv:

```sh
uv run python main.py
```

If dependencies changed, run `uv sync` from the project directory, then try `uv run main.py` again.
