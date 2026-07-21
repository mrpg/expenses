#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Track daily expenses against a monthly budget."""

import csv
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from functools import cache
from json import load
from typing import TypedDict, cast

import click

DAY = timedelta(days=1)
DAYS_PER_MONTH = Decimal("30.5")
CENT = Decimal("0.01")
EXPENSES = "expenses.csv"
HEADER = ("date", "amount", "description")

TODAY = date.today()


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


def prettyprint(
    sign: str,
    amount: Decimal,
    description: str | None = None,
    marker: str | None = None,
) -> None:
    if sign in ("=", "~", "D"):
        color = "green" if amount >= 0 else "red"
        sign_s = click.style(sign, fg=color, bold=True)
        amount_s = click.style(f"{amount:.2f}", fg=color, bold=True)
    elif sign == "+":
        sign_s = click.style(sign, fg="green")
        amount_s = click.style(f"{amount:.2f}", fg="green")
    else:
        sign_s = click.style(sign, fg="red")
        amount_s = click.style(f"{amount:.2f}", fg="red")

    fields = [sign_s, amount_s]

    if description:
        if sign == "+":
            fields.append(click.style(description, fg="cyan"))
        else:
            fields.append(click.style(description, fg="yellow"))

    if marker:
        fields.append(click.style(marker, bold=True))

    click.echo("\t".join(fields))


def print_day(day: date, highlighted_expense: int | None = None) -> None:
    prettyprint("+", daily_budget(), day.isoformat())

    for index, (amount, description) in enumerate(expenditures(day)):
        marker = "***" if index == highlighted_expense else None
        if amount < 0:
            prettyprint("+", -amount, description, marker)
        else:
            prettyprint("-", amount, description, marker)

    prettyprint("D", day_net(day))


def print_totals() -> None:
    click.echo(click.style("─" * 40, dim=True))
    prettyprint("=", balance())

    if day_nets():
        prettyprint("~", balance() / len(day_nets()))


def accounting(show_all: bool = False) -> None:
    days = day_nets() if show_all else {TODAY: day_net(TODAY)}
    for day in days:
        print_day(day)
        click.echo()

    print_totals()


@click.group(invoke_without_command=True)
@click.option("-a", "--all", "show_all", is_flag=True, help="Show all days.")
@click.pass_context
def cli(ctx: click.Context, show_all: bool) -> None:
    """Track daily expenses. Without a command, shows the report."""
    if ctx.invoked_subcommand is None:
        accounting(show_all)


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument("amount", type=DecimalType())
@click.argument("description")
@click.option(
    "--date",
    "date_",
    type=click.DateTime(["%Y-%m-%d"]),
    default=TODAY.isoformat(),
    show_default=True,
    help="Day the expense belongs to.",
)
def add(amount: Decimal, description: str, date_: datetime) -> None:
    """Add an expense or credit, e.g.: add 9.50 lunch or add -5 subsidy."""
    day = date_.date()

    with open(EXPENSES, "a", newline="") as f:
        writer = csv.writer(f)

        if f.tell() == 0:
            writer.writerow(HEADER)

        writer.writerow([day.isoformat(), f"{amount:.2f}", description])

    invalidate()
    new_entry = len(expenditures(day)) - 1
    print_day(day, highlighted_expense=new_entry)
    click.echo()
    print_totals()


@cli.command()
@click.option("-a", "--all", "show_all", is_flag=True, help="Show all days.")
def report(show_all: bool) -> None:
    """Show the running balance since the start date."""
    accounting(show_all)


if __name__ == "__main__":
    cli()
