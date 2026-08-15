#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Track daily expenses against a monthly budget."""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from functools import cached_property
from json import load
from pathlib import Path
from statistics import StatisticsError, stdev
from typing import Literal, TypeAlias, TypedDict, cast

import click

__all__ = ("accounting", "add_expenses", "cli", "configure", "info_report")

DAY = timedelta(days=1)
DAYS_PER_MONTH = Decimal("30.5")
CENT = Decimal("0.01")
Z_95 = Decimal("1.96")
EXPENSES = "expenses.csv"
HEADER = ("date", "amount", "description")

_data_dir = Path(".")

_Sign: TypeAlias = Literal["+", "-", "D", "=", "~"]


def _today() -> date:
    return datetime.now().astimezone().date()


class _Config(TypedDict):
    start: str
    income: dict[str, Decimal]
    costs: dict[str, Decimal]
    savingsTarget: Decimal


@dataclass
class _Invocation:
    """Data memoized for the lifetime of one external API call."""

    data_dir: Path
    today: date

    @cached_property
    def config(self) -> _Config:
        path = self.data_dir / "config.json"
        try:
            with open(path) as f:
                return cast(_Config, load(f, parse_float=Decimal, parse_int=Decimal))
        except FileNotFoundError:
            raise SystemExit(f"{path} not found.")

    @cached_property
    def start_date(self) -> date:
        return date.fromisoformat(self.config["start"])

    @cached_property
    def budget(self) -> Decimal:
        income = sum(self.config["income"].values(), start=Decimal(0))
        costs = sum(self.config["costs"].values(), start=Decimal(0))
        return income - costs

    @cached_property
    def daily_budget(self) -> Decimal:
        surplus = self.budget - self.config["savingsTarget"]
        return (surplus / DAYS_PER_MONTH).quantize(CENT, rounding=ROUND_FLOOR)

    @cached_property
    def all_expenditures(self) -> dict[date, list[tuple[Decimal, str]]]:
        expenditures: dict[date, list[tuple[Decimal, str]]] = {}

        try:
            with open(self.data_dir / EXPENSES, newline="") as f:
                reader = csv.reader(f)
                next(reader, None)

                for date_, amount, description in reader:
                    expenditures.setdefault(date.fromisoformat(date_), []).append(
                        (Decimal(amount), description)
                    )
        except FileNotFoundError:
            pass

        return expenditures

    def expenditures(self, date_: date) -> list[tuple[Decimal, str]]:
        return self.all_expenditures.get(date_, [])

    def day_net(self, day: date) -> Decimal:
        spent = sum((amount for amount, _ in self.expenditures(day)), start=Decimal(0))
        return self.daily_budget - spent

    @cached_property
    def day_nets(self) -> dict[date, Decimal]:
        days = (
            self.start_date + n * DAY
            for n in range((self.today - self.start_date).days + 1)
        )
        return {day: self.day_net(day) for day in days}

    @cached_property
    def balance(self) -> Decimal:
        return sum(self.day_nets.values(), start=Decimal(0))


class _DecimalType(click.ParamType[Decimal]):
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


def _parse_expense_pairs(
    ctx: click.Context, param: click.Parameter, values: tuple[str, ...]
) -> tuple[tuple[Decimal, str], ...]:
    if len(values) % 2:
        raise click.BadParameter(
            "each amount must be followed by a description.", ctx=ctx, param=param
        )

    amount_type = _DecimalType()
    return tuple(
        (amount_type.convert(amount, param, ctx), description)
        for amount, description in zip(values[::2], values[1::2])
    )


def configure(*, data_dir: str | Path | None = None) -> None:
    """Select the data directory used by subsequent API calls (default: cwd).

    Only the path is retained. Loaded configuration and expenditure data are not.
    """
    global _data_dir
    _data_dir = Path(".") if data_dir is None else Path(data_dir)


@dataclass(frozen=True, slots=True)
class _Row:
    sign: _Sign
    amount: Decimal
    description: str | None = None
    marker: str | None = None
    margin: Decimal | None = None


def _render_report(sections: list[list[_Row]], color: bool = True) -> str:
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

            if row.margin is not None:
                margin_s = click.style(f" ±{row.margin:.2f}", fg=fg, bold=bold)
                parts.append(margin_s)

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


def _day_rows(
    invocation: _Invocation,
    day: date,
    highlighted_expenses: range = range(0),
) -> list[_Row]:
    rows = [_Row("+", invocation.daily_budget, day.isoformat())]

    for index, (amount, description) in enumerate(invocation.expenditures(day)):
        marker = "***" if index in highlighted_expenses else None
        if amount < 0:
            rows.append(_Row("+", -amount, description, marker))
        else:
            rows.append(_Row("-", amount, description, marker))

    rows.append(_Row("D", invocation.day_net(day)))
    return rows


def _margin_of_error(daily_nets: list[Decimal]) -> Decimal | None:
    """Return the 95% margin for a daily mean, in the daily nets' units.

    Both the z-score and the square root of the sample count are dimensionless,
    so the result has the same currency-per-day unit as the sample mean.
    """
    try:
        standard_error = stdev(daily_nets) / Decimal(len(daily_nets)).sqrt()
        margin = Z_95 * standard_error
    except (ArithmeticError, StatisticsError, TypeError, ValueError):
        return None

    return margin if margin.is_finite() else None


def _total_rows(invocation: _Invocation) -> list[_Row]:
    total = invocation.balance
    rows = [_Row("=", total)]
    daily_nets = list(invocation.day_nets.values())
    if daily_nets:
        day_count = Decimal(len(daily_nets))
        daily_mean = total / day_count
        rows.append(_Row("~", daily_mean, margin=_margin_of_error(daily_nets)))
    return rows


def accounting(show_all: bool = False, color: bool = True) -> str:
    """Read the data files and return the current accounting report.

    File data may be memoized while this function runs, but nothing loaded is
    retained for a subsequent external API call.
    """
    invocation = _Invocation(_data_dir, _today())
    days = invocation.day_nets.keys() if show_all else (invocation.today,)
    sections = [_day_rows(invocation, day) for day in days]
    sections.append(_total_rows(invocation))
    return _render_report(sections, color=color)


def add_expenses(
    expenses_list: list[tuple[Decimal, str]],
    day: date | None = None,
    color: bool = True,
) -> str:
    """Append expenses to disk, then return a report from this call's data.

    File data may be memoized while this function runs, but nothing loaded is
    retained for a subsequent external API call.
    """
    invocation = _Invocation(_data_dir, _today())
    if day is None:
        day = invocation.today
    with open(invocation.data_dir / EXPENSES, "a", newline="") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(HEADER)
        writer.writerows(
            [day.isoformat(), f"{amount:.2f}", description]
            for amount, description in expenses_list
        )
    entry_count = len(invocation.expenditures(day))
    new_entries = range(entry_count - len(expenses_list), entry_count)
    return _render_report(
        [
            _day_rows(invocation, day, highlighted_expenses=new_entries),
            _total_rows(invocation),
        ],
        color=color,
    )


def info_report(color: bool = True) -> str:
    """Read config.json and return the income, costs, and allowance report.

    File data may be memoized while this function runs, but nothing loaded is
    retained for a subsequent external API call.
    """
    invocation = _Invocation(_data_dir, _today())
    config_ = invocation.config
    income = sum(config_["income"].values(), start=Decimal(0))
    costs = sum(config_["costs"].values(), start=Decimal(0))
    income_rows = [
        _Row("+", amount, name) for name, amount in config_["income"].items()
    ]
    income_rows.append(_Row("=", income, "total income"))
    cost_rows = [_Row("-", amount, name) for name, amount in config_["costs"].items()]
    cost_rows.append(_Row("=", -costs, "total costs"))
    savings_target = config_["savingsTarget"]
    return _render_report(
        [
            income_rows,
            cost_rows,
            [_Row("-", savings_target, "savings target")],
            [_Row("D", invocation.daily_budget, "daily budget")],
        ],
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


@cli.command("add", context_settings={"ignore_unknown_options": True})
@click.argument(
    "expense_pairs",
    nargs=-1,
    required=True,
    metavar="[AMOUNT DESCRIPTION]...",
    callback=_parse_expense_pairs,
)
@click.option(
    "--date",
    "date_",
    type=click.DateTime(["%Y-%m-%d"]),
    default=lambda: _today().isoformat(),
    show_default="today",
    help="Day the expense belongs to.",
)
def _add(expense_pairs: tuple[tuple[Decimal, str], ...], date_: datetime) -> None:
    """Add expenses or credits as AMOUNT DESCRIPTION pairs."""
    click.echo(add_expenses(list(expense_pairs), date_.date()))


@cli.command("report")
@click.option("-a", "--all", "show_all", is_flag=True, help="Show all days.")
def _report(show_all: bool) -> None:
    """Show the running balance since the start date."""
    click.echo(accounting(show_all))


@cli.command("info")
def _info() -> None:
    """Show monthly income, costs, and daily budget."""
    click.echo(info_report())


if __name__ == "__main__":
    cli()
