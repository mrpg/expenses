#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Track daily expenses against a monthly budget."""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from functools import cache
from json import load
from typing import Literal, TypeAlias, TypedDict, cast

import click

DAY = timedelta(days=1)
DAYS_PER_MONTH = Decimal("30.5")
CENT = Decimal("0.01")
EXPENSES = "expenses.csv"
HEADER = ("date", "amount", "description")

TODAY = date.today()

Sign: TypeAlias = Literal["+", "-", "D", "=", "~"]


class Config(TypedDict):
    start: str
    income: dict[str, Decimal]
    costs: dict[str, Decimal]
    savingsTarget: Decimal


@cache
def config() -> Config:
    try:
        with open("config.json") as f:
            return cast(Config, load(f, parse_float=Decimal, parse_int=Decimal))
    except FileNotFoundError:
        raise SystemExit("config.json not found in the current directory.")


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
        f = open(EXPENSES, newline="")
    except FileNotFoundError:
        return expenditures_

    with f:
        reader = csv.reader(f)
        next(reader, None)

        for date_, amount, description in reader:
            expenditures_.setdefault(date.fromisoformat(date_), []).append(
                (Decimal(amount), description)
            )

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
    for precalculated in (all_expenditures, day_nets, balance):
        precalculated.cache_clear()


@dataclass(frozen=True, slots=True)
class Row:
    sign: Sign
    amount: Decimal
    description: str | None = None
    marker: str | None = None


def render_report(sections: list[list[Row]]) -> None:
    width = max(len(f"{row.amount:.2f}") for rows in sections for row in rows)

    for section_index, rows in enumerate(sections):
        if section_index:
            click.echo()
        if section_index == len(sections) - 1:
            click.echo(click.style("─" * (width + 4), dim=True))

        for row in rows:
            amount_str = f"{row.amount:.2f}"
            is_summary = row.sign in ("=", "~", "D")
            is_positive = row.amount >= 0 if is_summary else row.sign == "+"
            color = "green" if is_positive else "red"
            bold = True if is_summary else None
            sign_s = click.style(row.sign, fg=color, bold=bold)
            amount_s = click.style(amount_str.rjust(width), fg=color, bold=bold)

            parts = [sign_s, "   ", amount_s]

            if row.description:
                color = "cyan" if row.sign == "+" else "yellow"
                parts.append("   ")
                parts.append(click.style(row.description, fg=color))

            if row.marker:
                parts.append("   ")
                parts.append(click.style(row.marker, bold=True))

            click.echo("".join(parts))


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


def accounting(show_all: bool = False) -> None:
    days = day_nets().keys() if show_all else (TODAY,)
    sections = [day_rows(day) for day in days]
    sections.append(total_rows())
    render_report(sections)


@click.group(invoke_without_command=True)
@click.option(
    "-a",
    "--all",
    "show_all",
    is_flag=True,
    help="Show all days (until today).",
)
@click.pass_context
def cli(ctx: click.Context, show_all: bool) -> None:
    """Track daily expenses. Without a command, shows the report."""
    if ctx.invoked_subcommand is None:
        accounting(show_all)


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
    day = date_.date()

    with open(EXPENSES, "a", newline="") as f:
        writer = csv.writer(f)

        if f.tell() == 0:
            writer.writerow(HEADER)

        writer.writerows(
            [day.isoformat(), f"{amount:.2f}", description]
            for amount, description in expense_pairs
        )

    invalidate()
    entry_count = len(expenditures(day))
    new_entries = range(entry_count - len(expense_pairs), entry_count)
    render_report([day_rows(day, highlighted_expenses=new_entries), total_rows()])


@cli.command()
@click.option("-a", "--all", "show_all", is_flag=True, help="Show all days.")
def report(show_all: bool) -> None:
    """Show the running balance since the start date."""
    accounting(show_all)


@cli.command()
def info() -> None:
    """Show monthly income, costs, and daily budget."""
    config_ = config()
    income = sum(config_["income"].values(), start=Decimal(0))
    costs = sum(config_["costs"].values(), start=Decimal(0))

    income_rows = [Row("+", amount, name) for name, amount in config_["income"].items()]
    income_rows.append(Row("=", income, "total income"))

    cost_rows = [Row("-", amount, name) for name, amount in config_["costs"].items()]
    cost_rows.append(Row("=", -costs, "total costs"))

    render_report([income_rows, cost_rows, [Row("D", daily_budget(), "daily budget")]])


if __name__ == "__main__":
    cli()
