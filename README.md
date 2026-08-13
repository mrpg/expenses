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

When your data is in the repository directory, run the installed entry point through
`uv`:

```console
$ uv run expenses add 9.50 lunch   # record an expense (today)
$ uv run expenses add -5 subsidy   # record a credit (today)
$ uv run expenses                  # report for today plus totals
$ uv run expenses -a               # report for all days since start
```

To record a past or future expense, use `--date`:

```console
$ uv run expenses add --date 2026-07-01 20 gift
```

You can also record multiple expenses:

```console
$ uv run expenses add 9.50 lunch 3 coffee
```

## Python API

The supported Python API consists of these functions:

```python
from expenses import accounting, add_expenses, configure, info_report
```

- `configure(*, data_dir=None)` selects the directory containing the data files.
- `accounting(show_all=False, color=True)` returns the current accounting report.
- `add_expenses(expenses_list, day=None, color=True)` records expenses and returns
  the resulting report. Each expense is a `(Decimal, str)` pair.
- `info_report(color=True)` returns the income, costs, and daily-budget report.

Each reporting or writing call starts a new data context and rereads the relevant
files. Values can be reused internally for consistency during that one call, but no
loaded configuration or expenditure data is retained for the next call. The `cli`
Click group is also exported as the package's console entry point; underscored names
are internal implementation details.

## Tip: wrapper scripts

It is often better to keep private financial data outside the source repository. Use
`--dir` to select the directory containing `config.json` and `expenses.csv`. You can
create little shell scripts in `~/.local/bin/` (or anywhere else in your `$PATH`),
and use `uv run --project` to select this project's environment:

```bash
#!/usr/bin/env bash

EXPENSES_PROJECT=/path/to/this/repo
EXPENSES_DATA=~/path/to/your/data
exec uv run --project "$EXPENSES_PROJECT" expenses --dir "$EXPENSES_DATA" "$@"
```

```bash
#!/usr/bin/env bash

EXPENSES_PROJECT=/path/to/this/repo
EXPENSES_DATA=~/path/to/your/data
exec uv run --project "$EXPENSES_PROJECT" expenses --dir "$EXPENSES_DATA" add "$@"
```

Name them `E` and `E+` and recording an expense becomes `E+ 9.50 lunch` — extraordinarily convenient. Moreover, `E` will show you today's report, and `E -a` will show the entire record.

## License

0BSD
