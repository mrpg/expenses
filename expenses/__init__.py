#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Track daily expenses against a monthly budget."""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from functools import cache
from json import load
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict, cast

import click

DAY = timedelta(days=1)
DAYS_PER_MONTH = Decimal("30.5")
CENT = Decimal("0.01")
EXPENSES = "expenses.csv"
HEADER = ("date", "amount", "description")

TODAY = datetime.now().astimezone().date()

_data_dir = Path(".")

Sign: TypeAlias = Literal["+", "-", "D", "=", "~"]


class Config(TypedDict):
    start: str
    income: dict[str, Decimal]
    costs: dict[str, Decimal]
    savingsTarget: Decimal


@cache
def config() -> Config:
    path = _data_dir / "config.json"
    try:
        with open(path) as f:
            return cast(Config, load(f, parse_float=Decimal, parse_int=Decimal))
    except FileNotFoundError:
        raise SystemExit(f"{path} not found.")


@cache
def start_date() -> date:
    return date.fromisoformat(config()["start"])


class DecimalType(click.ParamType[Decimal]):
    name = "decimal"

    def convert(
        self, value: str, param: click.Parameter | None, ctx: click.Context | None
    ) -> Decimal:
        try:
            amount = Decimal(value)
        except InvalidOperation:
            self.fail(f"{value!r} is not a valid amount.", param, ctx)

        if not amount.is_finite() or amount == 0:
            self.fail(f"{value!r} is not a finite, non-zero amount.", param, ctx)

        return amount


def parse_expense_pairs(
    ctx: click.Context, param: click.Parameter, values: tuple[str, ...]
) -> tuple[tuple[Decimal, str], ...]:
    if len(values) % 2:
        raise click.BadParameter(
            "each amount must be followed by a description.", ctx=ctx, param=param
        )

    amount_type = DecimalType()
    return tuple(
        (amount_type.convert(amount, param, ctx), description)
        for amount, description in zip(values[::2], values[1::2])
    )


def budget() -> Decimal:
    config_ = config()
    income = sum(config_["income"].values(), start=Decimal(0))
    costs = sum(config_["costs"].values(), start=Decimal(0))
    return income - costs


@cache
def daily_budget() -> Decimal:
    surplus = budget() - config()["savingsTarget"]
    return (surplus / DAYS_PER_MONTH).quantize(CENT, rounding=ROUND_FLOOR)


@cache
def all_expenditures() -> dict[date, list[tuple[Decimal, str]]]:
    expenditures_: dict[date, list[tuple[Decimal, str]]] = {}

    try:
        with open(_data_dir / EXPENSES, newline="") as f:
            reader = csv.reader(f)
            next(reader, None)

            for date_, amount, description in reader:
                expenditures_.setdefault(date.fromisoformat(date_), []).append(
                    (Decimal(amount), description)
                )
    except FileNotFoundError:
        return expenditures_

    return expenditures_


def expenditures(date_: date) -> list[tuple[Decimal, str]]:
    return all_expenditures().get(date_, [])


def day_net(day: date) -> Decimal:
    spent = sum((amount for amount, _ in expenditures(day)), start=Decimal(0))
    return daily_budget() - spent


@cache
def day_nets() -> dict[date, Decimal]:
    start = start_date()
    days = (start + n * DAY for n in range((TODAY - start).days + 1))
    return {day: day_net(day) for day in days}


@cache
def balance() -> Decimal:
    return sum(day_nets().values(), start=Decimal(0))


def invalidate() -> None:
    for fn in (config, start_date, daily_budget, all_expenditures, day_nets, balance):
        fn.cache_clear()


def configure(*, data_dir: str | Path | None = None) -> None:
    """Set the directory containing config.json and expenses.csv (default: cwd)."""
    global _data_dir
    _data_dir = Path(".") if data_dir is None else Path(data_dir)
    invalidate()


@dataclass(frozen=True, slots=True)
class Row:
    sign: Sign
    amount: Decimal
    description: str | None = None
    marker: str | None = None


def render_report(sections: list[list[Row]], color: bool = True) -> str:
    width = max(len(f"{row.amount:.2f}") for rows in sections for row in rows)
    desc_width = max(
        (
            len(row.description)
            for rows in sections
            for row in rows
            if row.marker and row.description
        ),
        default=0,
    )

    lines: list[str] = []
    for section_index, rows in enumerate(sections):
        if section_index:
            lines.append("")
        if section_index == len(sections) - 1:
            lines.append(click.style("─" * (width + 4), dim=True))

        for row in rows:
            amount_str = f"{row.amount:.2f}"
            is_summary = row.sign in ("=", "~", "D")
            is_positive = row.amount >= 0 if is_summary else row.sign == "+"
            fg = "green" if is_positive else "red"
            bold = True if is_summary else None
            sign_s = click.style(row.sign, fg=fg, bold=bold)
            amount_s = click.style(amount_str.rjust(width), fg=fg, bold=bold)

            parts = [sign_s, "   ", amount_s]

            if row.description:
                fg = "cyan" if row.sign == "+" else "yellow"
                desc = (
                    row.description.ljust(desc_width) if row.marker else row.description
                )
                parts.append("   ")
                parts.append(click.style(desc, fg=fg))

            if row.marker:
                parts.append("   ")
                parts.append(click.style(row.marker, bold=True))

            lines.append("".join(parts))

    result = "\n".join(lines)
    return result if color else click.unstyle(result)


def day_rows(day: date, highlighted_expenses: range = range(0)) -> list[Row]:
    rows = [Row("+", daily_budget(), day.isoformat())]

    for index, (amount, description) in enumerate(expenditures(day)):
        marker = "***" if index in highlighted_expenses else None
        if amount < 0:
            rows.append(Row("+", -amount, description, marker))
        else:
            rows.append(Row("-", amount, description, marker))

    rows.append(Row("D", day_net(day)))
    return rows


def total_rows() -> list[Row]:
    total = balance()
    rows = [Row("=", total)]
    nets = day_nets()
    if nets:
        rows.append(Row("~", total / len(nets)))
    return rows


def accounting(show_all: bool = False, color: bool = True) -> str:
    days = day_nets().keys() if show_all else (TODAY,)
    sections = [day_rows(day) for day in days]
    sections.append(total_rows())
    return render_report(sections, color=color)


def add_expenses(
    expenses_list: list[tuple[Decimal, str]],
    day: date | None = None,
    color: bool = True,
) -> str:
    if day is None:
        day = TODAY
    with open(_data_dir / EXPENSES, "a", newline="") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(HEADER)
        writer.writerows(
            [day.isoformat(), f"{amount:.2f}", description]
            for amount, description in expenses_list
        )
    invalidate()
    entry_count = len(expenditures(day))
    new_entries = range(entry_count - len(expenses_list), entry_count)
    return render_report(
        [day_rows(day, highlighted_expenses=new_entries), total_rows()],
        color=color,
    )


def info_report(color: bool = True) -> str:
    config_ = config()
    income = sum(config_["income"].values(), start=Decimal(0))
    costs = sum(config_["costs"].values(), start=Decimal(0))
    income_rows = [Row("+", amount, name) for name, amount in config_["income"].items()]
    income_rows.append(Row("=", income, "total income"))
    cost_rows = [Row("-", amount, name) for name, amount in config_["costs"].items()]
    cost_rows.append(Row("=", -costs, "total costs"))
    return render_report(
        [income_rows, cost_rows, [Row("D", daily_budget(), "daily budget")]],
        color=color,
    )


@click.group(invoke_without_command=True)
@click.option(
    "--dir",
    "data_dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Directory containing config.json and expenses.csv.",
)
@click.option(
    "-a",
    "--all",
    "show_all",
    is_flag=True,
    help="Show all days (until today).",
)
@click.pass_context
def cli(ctx: click.Context, data_dir: str | None, show_all: bool) -> None:
    """Track daily expenses. Without a command, shows the report."""
    configure(data_dir=data_dir)
    if ctx.invoked_subcommand is None:
        click.echo(accounting(show_all))


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument(
    "expense_pairs",
    nargs=-1,
    required=True,
    metavar="[AMOUNT DESCRIPTION]...",
    callback=parse_expense_pairs,
)
@click.option(
    "--date",
    "date_",
    type=click.DateTime(["%Y-%m-%d"]),
    default=TODAY.isoformat(),
    show_default=True,
    help="Day the expense belongs to.",
)
def add(expense_pairs: tuple[tuple[Decimal, str], ...], date_: datetime) -> None:
    """Add expenses or credits as AMOUNT DESCRIPTION pairs."""
    click.echo(add_expenses(list(expense_pairs), date_.date()))


@cli.command()
@click.option("-a", "--all", "show_all", is_flag=True, help="Show all days.")
def report(show_all: bool) -> None:
    """Show the running balance since the start date."""
    click.echo(accounting(show_all))


@cli.command()
def info() -> None:
    """Show monthly income, costs, and daily budget."""
    click.echo(info_report())


if __name__ == "__main__":
    cli()
