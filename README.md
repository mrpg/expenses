# expenses

[![Code style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A tiny command-line tool that tracks daily spending against a monthly budget.

Your monthly surplus (income minus fixed costs minus a savings target) is divided by 30.5 to get a daily allowance. Every day you get that allowance, every expense subtracts from it, and the tool shows the running balance since your start date. Stay green, and you are on track.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/)

The project requires Python 3.10 or newer. `uv` manages Python and installs Click from the locked project dependencies.

## Setup

Clone the project and create its environment:

```console
$ git clone https://github.com/mrpg/expenses.git
$ cd expenses
$ uv sync
```

The tool operates on the *current directory*. Put a `config.json` in the directory where you want to keep your expense data:

```json
{
    "start": "2026-01-01",
    "income": {
        "salary": 3000
    },
    "costs": {
        "rent": 1000,
        "insurance": 150
    },
    "savingsTarget": 500
}
```

Expenses are stored next to it in a plain `expenses.csv`, created automatically.

## Usage

When your data is in the repository directory, run the tool through `uv`:

```console
$ uv run main.py add 9.50 lunch   # record an expense (today)
$ uv run main.py                  # report for today plus totals
$ uv run main.py -a               # report for all days since start
```

To record a past or future expense, use `--date`:

```console
$ uv run main.py add --date 2026-07-01 20 gift
```

## Tip: wrapper scripts

It is often better to keep private financial data outside the source repository. Since the tool works on the current directory, you can create little shell scripts in `~/.local/bin/` (or anywhere else in your `$PATH`) that `cd` into your data directory first. `uv run --project` selects this project's environment without changing that working directory:

```bash
#!/usr/bin/env bash

cd ~/path/to/your/data || exit 2

EXPENSES_PROJECT=/path/to/this/repo
exec uv run --project "$EXPENSES_PROJECT" "$EXPENSES_PROJECT/main.py" "$@"
```

```bash
#!/usr/bin/env bash

cd ~/path/to/your/data || exit 2

EXPENSES_PROJECT=/path/to/this/repo
exec uv run --project "$EXPENSES_PROJECT" "$EXPENSES_PROJECT/main.py" add "$@"
```

Name them `E` and `E+` and recording an expense becomes `E+ 9.50 lunch` — extraordinarily convenient. Moreover, `E` will show you today's report, and `E -a` will show the entire record.

## License

0BSD
